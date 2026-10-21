#!/usr/bin/env python3
"""Bounded fair collection and small indexes for the complete event catalog."""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

from collect import (ROOT, UTC, USER_AGENT, ccu_url, error_code,
                     load_json, news_events, parse, parse_ccu, stamp)
from wishlist import build_index as build_wishlist_index

ACTIVE_CLIENT = None

class Paused(RuntimeError):
    """A budget, deadline or collection boundary; never a zero observation."""


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    temp.replace(path)


def state_path(root):
    return root / "site/data/collection-state.json"


def read_state(root):
    path = state_path(root)
    return load_json(path) if path.exists() else {
        "schema_version": 2, "ccu_cursor": 0, "news_cursor": 0,
        "reservations": {}, "last_run": None,
    }


def ccu_enabled(config):
    enabled = config['collection'].get('ccu_enabled', True)
    if type(enabled) is not bool:
        raise ValueError('ccu_enabled_must_be_boolean')
    return enabled


def request_limits(config, catalog, mode=None, full=False):
    settings = config['collection']
    mode = mode or settings.get('default_mode', 'both')
    if mode not in {'ccu', 'news', 'both'}:
        raise ValueError('invalid_collection_mode')
    mapped = sum(bool(g.get('demo_app_id')) for g in catalog['games'])
    sources = sum(len(set(filter(None, [g['app_id'], g.get('demo_app_id')])))
                  for g in catalog['games'])
    ccu = mapped * 2 if full else settings['ccu_request_budget']
    news = sources * 2 if full else settings['news_request_budget']
    if not ccu_enabled(config) or mode == 'news':
        ccu = 0
    if mode == 'ccu':
        news = 0
    return ccu, news


def collection_due(config, state, now=None):
    """Workflow-level concurrency makes this check precede any reservation."""
    now = now or datetime.now(UTC)
    if now >= parse(config["collection"]["stops_at"]):
        return True  # Always allow the final archive path, which makes no API calls.
    if now < parse(config["event"]["starts_at"]):
        return False
    previous = (state.get("last_run") or {}).get("started_at")
    return not previous or (now - parse(previous)).total_seconds() >= 15 * 60


def reserve(root, config, run_id, requested, now=None):
    """Reservations remain charged even if the runner is interrupted."""
    now = now or datetime.now(UTC)
    state = read_state(root)
    if run_id in state["reservations"]:
        return state["reservations"][run_id]
    day = now.date().isoformat()
    used = sum(x["allowance"] for x in state["reservations"].values() if x["day"] == day)
    available = max(0, int(config["collection"]["daily_request_budget"]) - used)
    in_window = parse(config["event"]["starts_at"]) <= now < parse(config["collection"]["stops_at"])
    lease = {"day": day, "allowance": min(requested, available) if in_window else 0,
             "used": 0, "created_at": stamp(now), "completed": False}
    state["reservations"][run_id] = lease
    save(state_path(root), state)
    return lease


class Client:
    def __init__(self, stop, allowance, *, spacing=.5, max_seconds=840,
                 clock=None, opener=None):
        self.clock = clock or (lambda: datetime.now(UTC))
        self.stop = stop
        self.allowance = allowance
        self.spacing = spacing
        self.deadline = time.monotonic() + max_seconds
        self.opener = opener or urllib.request.urlopen
        self.lock = threading.Lock()
        self.next_at = time.monotonic()
        self.used = 0
        self.failures = 0
        self.reason = None
        self.day = self.clock().date()

    def acquire(self, channel):
        while True:
            with self.lock:
                if self.reason:
                    raise Paused(self.reason)
                if self.clock() >= self.stop:
                    self.reason = "event_closed"
                    raise Paused(self.reason)
                if self.clock().date() != self.day:
                    self.reason = "utc_day_boundary"
                    raise Paused(self.reason)
                if time.monotonic() >= self.deadline:
                    self.reason = "runtime_budget"
                    raise Paused(self.reason)
                if self.used >= self.allowance:
                    self.reason = "request_budget"
                    raise Paused(self.reason)
                if channel["used"] >= channel["limit"]:
                    raise Paused("channel_budget")
                wait = self.next_at - time.monotonic()
                if wait <= 0:
                    self.next_at = time.monotonic() + self.spacing
                    self.used += 1
                    channel["used"] += 1
                    return
            time.sleep(min(max(wait, .01), .2))

    def get(self, url, channel):
        if not url.startswith("https://api.steampowered.com/"):
            raise ValueError("unsupported_source")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        previous_error = None
        for attempt in range(2):
            try:
                self.acquire(channel)
            except Paused:
                if previous_error:
                    raise previous_error
                raise
            try:
                with self.opener(request, timeout=12) as response:
                    payload = response.read(2_000_001)
                    if len(payload) > 2_000_000:
                        raise ValueError("response_too_large")
                    data = json.loads(payload)
                    if not isinstance(data, dict):
                        raise ValueError("invalid_response")
                with self.lock:
                    self.failures = 0
                return data
            except (urllib.error.URLError, TimeoutError, ValueError) as error:
                previous_error = error
                code = getattr(error, "code", None)
                with self.lock:
                    self.failures += 1
                    if code == 429:
                        raw = error.headers.get("Retry-After", "30") if error.headers else "30"
                        delay = min(120, max(30, int(raw))) if raw.isdigit() else 60
                        self.next_at = max(self.next_at, time.monotonic() + delay)
                    if code in (401, 403) or self.failures >= 8:
                        self.reason = "source_backoff"
                if attempt or self.reason or (code and code not in (429, 500, 502, 503, 504)):
                    raise
        raise RuntimeError("request_failed")


def history_path(root, game_id):
    return root / "site/data/games" / f"{game_id}.json"


def blank_history(now):
    return {"schema_version": 1, "generated_at": stamp(now), "collection_status": "active",
            "archived_at": None, "samples": [], "events": [], "analyses": [],
            "news_status": {}, "news_last_attempt_at": {}, "notices": []}


def valid(sample):
    return sample.get("status") == "ok" and type(sample.get("value")) is int and sample["value"] >= 0


def target_minutes(config, catalog, game_id):
    if game_id in config["collection"].get("priority_game_ids", []):
        return int(config["collection"]["interval_minutes"])
    count = sum(bool(g.get("demo_app_id")) for g in catalog["games"])
    budget = max(1, config["collection"]["ccu_request_budget"] -
                 len(config["collection"].get("priority_game_ids", [])))
    return math.ceil(count / budget) * int(config["collection"]["interval_minutes"])


def adjacent(a, b, gap_minutes):
    elapsed = (parse(b["observed_at"]) - parse(a["observed_at"])).total_seconds() / 60
    if not valid(a) or not valid(b) or not 0 < elapsed <= gap_minutes:
        return None
    delta = b["value"] - a["value"]
    return {"from": a["observed_at"], "to": b["observed_at"],
            "start_value": a["value"], "end_value": b["value"], "delta": delta,
            "percent": delta / a["value"] * 100 if a["value"] else None,
            "elapsed_minutes": elapsed}


def range_summary(samples, start, end, gap_minutes):
    rows = sorted((s for s in samples if start <= parse(s["observed_at"]) <= end),
                  key=lambda s: s["observed_at"])
    good = [s for s in rows if valid(s)]
    increases = [x for a, b in zip(rows, rows[1:])
                 if (x := adjacent(a, b, gap_minutes)) and x["delta"] > 0]
    compact = lambda s: {"observed_at": s["observed_at"], "value": s["value"]}
    return {"from": stamp(start), "to": stamp(end),
            "first": compact(good[0]) if good else None,
            "last": compact(good[-1]) if good else None,
            "peak": max((s["value"] for s in good), default=None),
            "valid_count": len(good),
            "latest_adjacent": adjacent(rows[-2], rows[-1], gap_minutes) if len(rows) > 1 else None,
            "max_increase": max(increases, key=lambda x: (x["delta"], x["to"]), default=None),
            "positive_intervals": len(increases)}


def observation_history(samples, end):
    """Stored CCU history, not a regularized series or growth-pair calculation."""
    rows = sorted((s for s in samples if s['metric'] == 'demo_ccu' and
                   parse(s['observed_at']) <= end), key=lambda s: s['observed_at'])
    good = [s for s in rows if valid(s)]

    def intervals(records):
        gaps = [(parse(b['observed_at']) - parse(a['observed_at'])).total_seconds() / 60
                for a, b in zip(records, records[1:])]
        return (gaps[-1], statistics.median(gaps)) if gaps else (None, None)

    last_attempt, median_attempt = intervals(rows)
    last_valid, median_valid = intervals(good)
    return {'attempt_count': len(rows), 'valid_count': len(good),
            'error_count': sum(s['status'] == 'error' for s in rows),
            'first_attempt_at': rows[0]['observed_at'] if rows else None,
            'first_valid_at': good[0]['observed_at'] if good else None,
            'latest_attempt_interval_minutes': last_attempt,
            'median_attempt_interval_minutes': median_attempt,
            'latest_valid_interval_minutes': last_valid,
            'median_valid_interval_minutes': median_valid}


def news_history(events):
    # Publication dates describe preserved evidence, not collection attempt cadence.
    events = [e for e in events if e.get('kind') in {'announcement', 'update'}]
    published = sorted(e['published_at'] for e in events if e.get('published_at'))
    return {'event_count': len(events),
            'first_published_at': published[0] if published else None,
            'last_published_at': published[-1] if published else None}


def collection_metadata(config, catalog):
    settings = config['collection']
    sources = sum(len(set(filter(None, [g['app_id'], g.get('demo_app_id')])))
                  for g in catalog['games'])
    budget = settings['news_request_budget']
    return {'scheduled_interval_minutes': settings['interval_minutes'],
            'target_cycle_minutes': target_minutes(config, catalog, '__all__'),
            'news_source_count': sources,
            'news_target_cycle_minutes': (math.ceil(sources / budget) * settings['interval_minutes']
                                          if budget > 0 else None),
            'cadence_basis': 'configured_budget_rotation_not_guaranteed',
            'ccu_collection': {'enabled': ccu_enabled(config),
                               'mode': 'scheduled' if ccu_enabled(config) else 'stopped_preserved_history'},
            'wishlist_numeric_collection': {'mode': 'reviewed_disclosures_only',
                                            'scheduled': False,
                                            'target_interval_minutes': None}}


def build_indexes(root, config=None, catalog=None, now=None):
    config = config or load_json(root / "config/manifest.json")
    catalog = catalog or load_json(root / "site/data/catalog.json")
    # Window calculations must use the same second precision as published timestamps.
    now = parse(stamp(now or datetime.now(UTC)))
    start, stop = parse(config["event"]["starts_at"]), parse(config["collection"]["stops_at"])
    end = min(now, stop)
    collected, events, wishlist_events = [], {}, []
    coverage = dict.fromkeys(["catalog_total", "demo_resolved", "ccu_attempted", "ccu_ok",
                              "ccu_pending", "ccu_error", "ccu_unavailable", "comparison_ready",
                              "news_checked", "news_pending", "growth_candidate_games",
                              "reviewed_games"], 0)
    coverage["catalog_total"] = len(catalog["games"])
    collection = config["collection"].copy()
    collection.update(collection_metadata(config, catalog))
    full_interval = collection["target_cycle_minutes"]
    for game in catalog["games"]:
        gid = game["id"]
        path = history_path(root, gid)
        history = load_json(path) if path.exists() else blank_history(now)
        rows = sorted((s for s in history["samples"] if s["metric"] == "demo_ccu"),
                      key=lambda s: s["observed_at"])
        good = [s for s in rows if valid(s)]
        last = rows[-1] if rows else None
        latest = good[-1] if good else None
        status = last["status"] if last else ("pending" if game.get("demo_app_id") else "unavailable")
        interval = (int(collection["interval_minutes"]) if gid in collection.get("priority_game_ids", [])
                    else full_interval)
        ranges = {key: range_summary(rows, start if key == "all" else max(start, end - timedelta(hours=int(key))),
                                    end, interval * 2 + 30) for key in ("all", "6", "24")}
        news = history.get("news_status", {}).get(gid, {})
        collected.append({"game_id": gid, "target_interval_minutes": interval, "status": status,
                          "ccu_collection_enabled": ccu_enabled(config),
                          "last_attempt_at": last["observed_at"] if last else None,
                          "last_ok_at": latest["observed_at"] if latest else None,
                          "current": latest["value"] if latest else None,
                          "last_error_code": last.get("error_code") if last else None,
                          "observation_history": observation_history(rows, end),
                          "news_history": news_history(history['events']),
                          "ranges": ranges, "news_status": news.get("status", "pending"),
                          "last_news_attempt_at": news.get("last_attempt_at"),
                          "news_all_checked_at": news.get("all_sources_checked_at"),
                          "news_error_codes": news.get("error_codes", []),
                          "history_url": f"./data/games/{gid}.json"})
        coverage["demo_resolved"] += bool(game.get("demo_app_id"))
        coverage["ccu_attempted"] += bool(rows)
        coverage["ccu_ok"] += bool(good)
        coverage["ccu_pending"] += status == "pending"
        coverage["ccu_error"] += status == "error"
        coverage["ccu_unavailable"] += status == "unavailable"
        coverage["comparison_ready"] += any(adjacent(a, b, interval * 2 + 30) is not None
                                            for a, b in zip(rows, rows[1:]))
        coverage["growth_candidate_games"] += ranges["all"]["positive_intervals"] > 0
        coverage["reviewed_games"] += bool(history["analyses"])
        coverage["news_checked"] += news.get("status") == "ok"
        coverage["news_pending"] += not bool(news.get("last_attempt_at"))
        for event in history["events"]:
            events[event["id"]] = {k: event.get(k) for k in (
                "id", "game_id", "kind", "title", "occurred_at", "published_at",
                "time_precision", "source_url", "verified_at")}
        wishlist_events.extend(history['events'])
    state = read_state(root)
    if now >= stop and not state.get("archived_at"):
        state["archived_at"] = stamp(now)
        save(state_path(root), state)
    summary = {"schema_version": 2, "generated_at": stamp(now), "window_end": stamp(end),
               "collection_status": "archived" if now >= stop else "pending" if now < start else "active",
               "archived_at": state.get("archived_at") if now >= stop else None,
               "last_attempt_at": (state.get("last_run") or {}).get("started_at"),
               "coverage": coverage, "collection": collection,
               "last_run": state.get("last_run"), "games": collected}
    save(root / "site/data/summary.json", summary)
    save(root / "site/data/events-index.json", {"schema_version": 2, "generated_at": stamp(now),
         "events": sorted(events.values(), key=lambda e: e.get("published_at") or "", reverse=True)})
    save(root / "site/data/config.json", config)
    save(root / "site/data/wishlists.json", build_wishlist_index(root, catalog, now, events=wishlist_events))
    return summary


def rotated(items, cursor):
    if not items:
        return []
    at = cursor % len(items)
    return items[at:] + items[:at]


def collect_fleet(root, *, full=False, mode=None, run_id=None, spacing=None,
                  max_seconds=840, client_factory=Client, missing_only=False):
    global ACTIVE_CLIENT
    config = load_json(root / "config/manifest.json")
    catalog = load_json(root / "site/data/catalog.json")
    now = datetime.now(UTC)
    stop = parse(config["collection"]["stops_at"])
    settings = config["collection"]
    if not parse(config["event"]["starts_at"]) <= now < stop:
        return build_indexes(root, config, catalog, now)
    run_id = run_id or "local-" + uuid.uuid4().hex
    games = catalog["games"]
    mapped = [g for g in games if g.get("demo_app_id")]
    news_sources = [(g, app) for g in games for app in dict.fromkeys(filter(None, [g["app_id"], g.get("demo_app_id")]))]
    ccu_limit, news_limit = request_limits(config, catalog, mode, full)
    if not ccu_limit and not news_limit:
        return build_indexes(root, config, catalog, now)
    lease = reserve(root, config, run_id, ccu_limit + news_limit)
    state = read_state(root)
    if lease["completed"]:
        return build_indexes(root, config, catalog, now)
    if lease["day"] != now.date().isoformat() or lease.get("started_at"):
        raise ValueError("incomplete_or_expired_lease_use_new_run_id")
    state["reservations"][run_id]["started_at"] = stamp(now)
    save(state_path(root), state)
    client = client_factory(stop, max(0, lease["allowance"] - lease["used"]),
                            spacing=spacing or settings["min_request_interval_seconds"],
                            max_seconds=max_seconds)
    ACTIVE_CLIENT = client
    channel_ccu, channel_news = {"used": 0, "limit": ccu_limit}, {"used": 0, "limit": news_limit}
    histories = {}
    history_lock = threading.Lock()

    def get_history(gid):
        with history_lock:
            if gid not in histories:
                path = history_path(root, gid)
                histories[gid] = load_json(path) if path.exists() else blank_history(now)
            return histories[gid]

    def save_history(gid):
        hist = get_history(gid)
        hist["samples"].sort(key=lambda s: (s["observed_at"], s["metric"]))
        hist["events"].sort(key=lambda e: e.get("published_at") or "", reverse=True)
        hist["generated_at"] = stamp(datetime.now(UTC))
        save(history_path(root, gid), hist)

    def observe(game):
        if not ccu_enabled(config):
            return 'skip'
        gid = game["id"]
        hist = get_history(gid)
        if missing_only and any(s["metric"] == "demo_ccu" for s in hist["samples"]):
            return "skip"
        at = datetime.now(UTC)
        interval = int(settings["interval_minutes"]) * 60
        slot = int(at.timestamp()) // interval
        if any(s["metric"] == "demo_ccu" and int(parse(s["observed_at"]).timestamp()) // interval == slot
               for s in hist["samples"]):
            return "skip"
        url = ccu_url(game["demo_app_id"])
        sample = {"game_id": gid, "metric": "demo_ccu", "observed_at": stamp(at),
                  "value": None, "status": "error", "source_url": url, "error_code": None}
        try:
            sample["value"] = parse_ccu(client.get(url, channel_ccu))
            sample["status"] = "ok"
        except Paused:
            return "paused"
        except Exception as error:
            sample["error_code"] = error_code(error)
        finished = datetime.now(UTC)
        if finished >= stop:
            return "paused"
        sample["observed_at"] = stamp(finished)
        hist["samples"].append(sample)
        save_history(gid)
        return "attempted"

    priority = settings.get("priority_game_ids", [])
    fair_games = mapped if full else [g for g in mapped if g["id"] not in priority]
    cursor_key = "full_ccu_cursor" if full else "ccu_cursor"
    cursor = state.get(cursor_key, 0)
    ordered = rotated(fair_games, cursor)
    ccu_games = ([g for g in mapped if g["id"] in priority] +
                 ordered) if not full else ordered
    ccu_games = ccu_games[:len(mapped) if full else max(0, ccu_limit)]
    progressed = 0
    outcomes = {}
    started = stamp(now)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(observe, g): g for g in ccu_games} if ccu_limit else {}
        for future in as_completed(futures):
            game = futures[future]
            outcomes[game["id"]] = future.result()
            if (client.used and client.used % 100 == 0):
                print(f"CCU requests={client.used} completed={len(outcomes)}", flush=True)
    # Only the contiguous completed prefix advances, including already-observed skips.
    for game in ordered:
        if outcomes.get(game["id"]) not in ("skip", "attempted"):
            break
        progressed += 1
    state[cursor_key] = (cursor + progressed) % max(1, len(fair_games))

    news_processed = 0
    source_statuses = {}
    for game, app_id in rotated(news_sources, state["news_cursor"]):
        if not news_limit or channel_news["used"] >= news_limit or client.reason:
            break
        gid = game["id"]
        hist = get_history(gid)
        prior_source = hist.get("news_sources", {}).get(str(app_id), {})
        verified = stamp(datetime.now(UTC))
        url = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
               f"?appid={app_id}&count=20&maxlength=1200&feeds=steam_community_announcements")
        try:
            found = news_events(client.get(url, channel_news), gid, verified)
            existing = {e["id"] for e in hist["events"]}
            hist["events"].extend(e for e in found if e["id"] not in existing)
            status = {"last_attempt_at": verified, "last_success_at": verified,
                      "status": "ok", "error_codes": []}
        except Paused:
            break
        except Exception as error:
            status = {"last_attempt_at": verified,
                      "last_success_at": prior_source.get("last_success_at"),
                      "status": "error", "error_codes": [error_code(error)]}
        if datetime.now(UTC) >= stop:
            break
        source_statuses.setdefault(gid, {})[str(app_id)] = status
        previous = hist.get("news_sources", {}).copy()
        previous.update(source_statuses[gid])
        hist["news_sources"] = previous
        required = set(map(str, filter(None, [game["app_id"], game.get("demo_app_id")])))
        complete = required.issubset(previous)
        errors = [code for value in previous.values() for code in value.get("error_codes", [])]
        successes = [previous.get(key, {}).get("last_success_at") for key in required]
        hist["news_status"][gid] = {"last_attempt_at": verified,
                                  "status": "error" if errors else "ok" if complete else "partial",
                                  "all_sources_checked_at": min(successes) if all(successes) else None,
                                  "error_codes": errors}
        hist["news_last_attempt_at"][gid] = verified
        save_history(gid)
        news_processed += 1
    state["news_cursor"] = (state["news_cursor"] + news_processed) % max(1, len(news_sources))
    finished = datetime.now(UTC)
    state["reservations"][run_id]["used"] += client.used
    state["reservations"][run_id]["completed"] = True
    state["last_run"] = {"run_id": run_id, "started_at": started, "finished_at": stamp(finished),
                         "ccu_requests": channel_ccu["used"], "news_requests": channel_news["used"],
                         "request_count": client.used, "reserved_requests": lease["allowance"],
                         "pause_reason": client.reason,
                         "ccu_games_attempted": sum(v == "attempted" for v in outcomes.values()),
                         "news_sources_attempted": news_processed}
    save(state_path(root), state)
    return build_indexes(root, config, catalog, finished)


def main():
    def interrupt(_signal, _frame):
        if ACTIVE_CLIENT:
            ACTIVE_CLIENT.reason = "interrupted"
        else:
            raise SystemExit(130)
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--mode", choices=["ccu", "news", "both"])
    parser.add_argument("--run-id")
    parser.add_argument("--spacing", type=float)
    parser.add_argument("--max-seconds", type=int, default=840)
    parser.add_argument("--reserve-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--check-due", action="store_true")
    args = parser.parse_args()
    config = load_json(args.root / "config/manifest.json")
    if args.check_due:
        due = collection_due(config, read_state(args.root))
        print(json.dumps({"due": due, "minimum_interval_minutes": 15}))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"due={'true' if due else 'false'}\n")
        return
    if args.reserve_only:
        if not args.run_id:
            parser.error("--reserve-only requires --run-id")
        catalog = load_json(args.root / 'site/data/catalog.json')
        ccu_limit, news_limit = request_limits(config, catalog, args.mode, args.full)
        lease = reserve(args.root, config, args.run_id, ccu_limit + news_limit)
        print(json.dumps(lease))
        return
    summary = (build_indexes(args.root) if args.build_only else
               collect_fleet(args.root, full=args.full, mode=args.mode, run_id=args.run_id,
                             spacing=args.spacing, max_seconds=args.max_seconds,
                             missing_only=args.missing_only))
    print(json.dumps({"coverage": summary["coverage"], "last_run": summary["last_run"]}))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"archived={'true' if summary['collection_status'] == 'archived' else 'false'}\n")


if __name__ == "__main__":
    main()
