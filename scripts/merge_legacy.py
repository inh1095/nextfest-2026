#!/usr/bin/env python3
"""Carry forward immutable original observations after switching collectors."""
import argparse
import copy
from datetime import datetime
from pathlib import Path

from collect import ROOT, UTC, load_json, stamp
from fleet import history_path, save


def key(field, item):
    if field == "samples":
        return item["game_id"], item["metric"], item["observed_at"]
    if field == "analyses":
        return item["game_id"], item["from"], item["to"], item["reviewed_at"]
    return item["id"]


def merge_history(history, legacy, gid):
    """Prepare the complete merge before writing; conflicting evidence is fatal."""
    merged = copy.deepcopy(history)
    added = 0
    for field in ("samples", "events", "analyses"):
        items = {key(field, item): item for item in merged[field]}
        for item in legacy[field]:
            if item["game_id"] != gid:
                continue
            identity = key(field, item)
            if identity in items and items[identity] != item:
                raise ValueError(f"conflicting_legacy_{field}:{gid}")
            if identity not in items:
                merged[field].append(copy.deepcopy(item))
                items[identity] = item
                added += 1
    # Preserve the newest aggregate status until per-source collection takes over.
    if not merged.get("news_sources"):
        old = legacy.get("news_status", {}).get(gid)
        current = merged.get("news_status", {}).get(gid, {})
        if old and (old.get("last_attempt_at") or "") > (current.get("last_attempt_at") or ""):
            merged.setdefault("news_status", {})[gid] = copy.deepcopy(old)
            merged.setdefault("news_last_attempt_at", {})[gid] = old["last_attempt_at"]
    merged["samples"].sort(key=lambda x: (x["observed_at"], x["metric"]))
    merged["events"].sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return merged, added


def merge_legacy(root):
    legacy = load_json(root / "site/data/observations.json")
    config = load_json(root / "config/manifest.json")
    prepared = []
    for game in config["games"]:
        path = history_path(root, game["id"])
        before = load_json(path)
        after, added = merge_history(before, legacy, game["id"])
        if after != before:
            after["generated_at"] = stamp(datetime.now(UTC))
            prepared.append((path, after, added))
    for path, after, added in prepared:
        save(path, after)
    return sum(item[2] for item in prepared)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(f"Merged {merge_legacy(args.root)} retained records.")
