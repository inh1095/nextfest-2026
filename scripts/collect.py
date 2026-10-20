#!/usr/bin/env python3
"""Append verified Steam observations. No LLM, credentials or database required."""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
USER_AGENT = "NextFestObservation/1.0 (+https://github.com/inh1095/nextfest-2026)"

class CollectionClosed(RuntimeError):
    pass


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(UTC)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_json(url: str, *, cutoff: datetime | None = None, clock=None) -> dict:
    """Small bounded requests; only official Steam hosts are accepted."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "api.steampowered.com":
        raise ValueError("unsupported_source")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    clock = clock or (lambda: datetime.now(UTC))
    for attempt in range(2):
        if cutoff is not None and clock() >= cutoff:
            raise CollectionClosed("collection_window_closed")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != 200:
                    raise ValueError("unexpected_http_status")
                payload = response.read(2_000_001)
                if len(payload) > 2_000_000:
                    raise ValueError("response_too_large")
                data = json.loads(payload)
                if not isinstance(data, dict):
                    raise ValueError("unexpected_response_type")
                return data
        except urllib.error.HTTPError as error:
            if attempt == 0 and (error.code == 429 or error.code >= 500):
                time.sleep(2)
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 0:
                time.sleep(2)
                continue
            raise
    raise RuntimeError("request_failed")


def error_code(error: Exception) -> str:
    # Never store response bodies, request headers or credentials in public files.
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    if isinstance(error, (urllib.error.URLError, TimeoutError)):
        return "network_error"
    if isinstance(error, (ValueError, KeyError, TypeError)):
        return "invalid_response"
    return "collection_error"


def ccu_url(app_id: int) -> str:
    return f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={app_id}"


def parse_ccu(payload: dict) -> int:
    response = payload.get("response")
    if not isinstance(response, dict) or response.get("result") != 1:
        raise ValueError("unsuccessful_steam_result")
    count = response.get("player_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("invalid_player_count")
    return count


def plain_text(content: str, limit: int = 500) -> str:
    content = re.sub(r"<[^>]*>", " ", str(content))
    content = re.sub(r"\[(?:/?[a-zA-Z][^\]]*)\]", " ", content)
    return re.sub(r"\s+", " ", html.unescape(content)).strip()[:limit]


def news_events(payload: dict, game_id: str, verified_at: str) -> list[dict]:
    appnews = payload.get("appnews")
    if not isinstance(appnews, dict) or not isinstance(appnews.get("newsitems"), list):
        raise ValueError("invalid_news_response")
    events = []
    for item in appnews["newsitems"]:
        if item.get("feedname") != "steam_community_announcements":
            continue
        source = str(item.get("url", ""))
        parts = urllib.parse.urlsplit(source)
        official_link = parts.hostname in {"store.steampowered.com", "steamcommunity.com", "www.steamcommunity.com"}
        official_news_redirect = (
            parts.hostname == "steamstore-a.akamaihd.net"
            and re.fullmatch(r"/news/externalpost/steam_community_announcements/\d+/?", parts.path)
        )
        if parts.scheme != "https" or not (official_link or official_news_redirect):
            continue
        published = item.get("date")
        gid = str(item.get("gid", ""))
        if not gid.isdigit() or isinstance(published, bool) or not isinstance(published, (int, float)):
            continue
        title = plain_text(item.get("title", ""), 250)
        if not title:
            continue
        try:
            published_at = stamp(datetime.fromtimestamp(published, UTC))
        except (ValueError, OSError, OverflowError):
            continue
        kind = "update" if re.search(r"\b(patch|hotfix|update)\b", title, re.I) else "announcement"
        events.append({
            "id": f"steam-{game_id}-{gid}", "game_id": game_id, "kind": kind,
            "title": title, "summary": plain_text(item.get("contents", "")),
            # A publication time does not establish when an announced event occurred.
            "occurred_at": None, "published_at": published_at, "time_precision": "minute",
            "source_url": source, "verified_at": verified_at,
            "discovery_method": "official_steam_news", "content_review": "source_only",
        })
    return events


def sample_slot(sample: dict, interval_seconds: int) -> int:
    return int(parse(sample["observed_at"]).timestamp()) // interval_seconds


def collect(config: dict, data: dict, *, now: datetime | None = None, fetch=fetch_json) -> dict:
    fixed_clock = now is not None
    now = now or datetime.now(UTC)
    observed = stamp(now)
    start = parse(config["event"]["starts_at"])
    stop = parse(config["collection"]["stops_at"])
    data.setdefault("schema_version", 1)
    data.setdefault("samples", [])
    data.setdefault("events", [])
    data.setdefault("analyses", [])
    data.setdefault("notices", [])
    data.setdefault("news_last_attempt_at", {})
    data.setdefault("news_status", {})
    data.setdefault("archived_at", None)
    if now >= stop:
        if data.get("collection_status") != "archived":
            data.update(collection_status="archived", archived_at=observed,
                        generated_at=observed, last_attempt_at=observed)
        return data  # No network access or fictional end-of-event samples.
    if now < start:
        data.update(collection_status="pending", generated_at=observed, last_attempt_at=observed)
        return data

    data.update(collection_status="active", last_attempt_at=observed)
    interval = int(config["collection"]["interval_minutes"]) * 60
    slot = int(now.timestamp()) // interval
    news_interval = int(config["collection"]["news_interval_minutes"]) * 60

    def in_window_fetch(url):
        if (now if fixed_clock else datetime.now(UTC)) >= stop:
            raise CollectionClosed("collection_window_closed")
        return fetch(url, cutoff=stop) if fetch is fetch_json else fetch(url)

    for game in config["games"]:
        game_id = game["id"]
        for metric in game["metrics"]:
            key = metric["key"]
            prior = [s for s in data["samples"] if s["game_id"] == game_id and s["metric"] == key]
            if metric["availability"] != "available":
                if not prior:
                    data["samples"].append({
                        "game_id": game_id, "metric": key, "observed_at": observed,
                        "value": None, "status": "unavailable",
                        "source_url": metric["source_url"], "error_code": "source_unverified",
                    })
                continue
            if key != "demo_ccu":
                raise ValueError("unimplemented_metric")
            if any(sample_slot(s, interval) == slot for s in prior):
                continue
            source = ccu_url(game["demo_app_id"])
            sample = {"game_id": game_id, "metric": key, "observed_at": observed,
                      "value": None, "status": "error", "source_url": source, "error_code": None}
            try:
                sample["value"] = parse_ccu(in_window_fetch(source))
                sample["status"] = "ok"
            except Exception as error:
                sample["error_code"] = error_code(error)
            sample["observed_at"] = observed if fixed_clock else stamp(datetime.now(UTC))
            # A request completing after the collection cutoff is not added.
            if parse(sample["observed_at"]) < stop:
                data["samples"].append(sample)
        actual_now = now if fixed_clock else datetime.now(UTC)
        if actual_now >= stop:
            break
        last_news = data["news_last_attempt_at"].get(game_id)
        if last_news and (actual_now - parse(last_news)).total_seconds() < news_interval:
            continue
        verified = stamp(actual_now)
        data["news_last_attempt_at"][game_id] = verified
        failures = []
        for app_id in dict.fromkeys([game["app_id"], game["demo_app_id"]]):
            if not fixed_clock and datetime.now(UTC) >= stop:
                break
            source = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
                      f"?appid={app_id}&count=20&maxlength=2000&feeds=steam_community_announcements")
            try:
                found = news_events(in_window_fetch(source), game_id, verified)
                existing = {event["id"] for event in data["events"]}
                for event in found:
                    if event["id"] not in existing:
                        data["events"].append(event)
                        existing.add(event["id"])
            except Exception as error:
                failures.append(error_code(error))
        data["news_status"][game_id] = {
            "last_attempt_at": verified, "status": "error" if failures else "ok",
            "error_codes": failures,
        }
    data["samples"].sort(key=lambda s: (s["observed_at"], s["game_id"], s["metric"]))
    data["events"].sort(key=lambda e: (e.get("published_at") or "", e["id"]), reverse=True)
    finished = now if fixed_clock else datetime.now(UTC)
    data["generated_at"] = stamp(finished)
    if finished >= stop:
        data.update(collection_status="archived", archived_at=stamp(finished))
    return data


def export_csv(data: dict, path: Path) -> None:
    fields = ["game_id", "metric", "observed_at", "value", "status", "source_url", "error_code"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(data["samples"])
    path.write_text(output.getvalue(), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    config = load_json(args.root / "config/manifest.json")
    target = args.root / "site/data/observations.json"
    data = load_json(target) if target.exists() else {}
    updated = collect(config, data)
    write_json(target, updated)
    write_json(args.root / "site/data/config.json", config)
    export_csv(updated, args.root / "site/data/observations.csv")
    archive = updated["collection_status"] == "archived"
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"archived={'true' if archive else 'false'}\n")
    print(json.dumps({
        "status": updated["collection_status"], "sample_count": len(updated["samples"]),
        "event_count": len(updated["events"]), "last_attempt_at": updated["last_attempt_at"],
    }))


if __name__ == "__main__":
    main()
