#!/usr/bin/env python3
"""Import a SOL-verified official catalog without altering retained observations."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from collect import ROOT, UTC, load_json, parse, stamp
from fleet import blank_history, build_indexes, history_path, read_state, save, state_path


def import_catalog(root, source, evidence_path):
    rows = load_json(source)
    evidence = load_json(evidence_path)
    config = load_json(root / "config/manifest.json")
    initial = load_json(root / "site/data/observations.json")
    expected = evidence["enumeration"]["tagged_unique_appids"]
    app_ids = [row["app_id"] for row in rows]
    if len(app_ids) != expected or len(set(app_ids)) != expected:
        raise ValueError("catalog_membership_count_mismatch")
    if not evidence["enumeration"]["arrays_set_equal"]:
        raise ValueError("official_membership_crosscheck_failed")
    seeds = {g["app_id"]: g for g in config["games"]}
    if not set(seeds).issubset(app_ids):
        raise ValueError("retained_games_missing_from_catalog")
    now = datetime.now(UTC)
    source_url = evidence["source_url"]
    games = []
    for row in sorted(rows, key=lambda r: r["app_id"]):
        old = seeds.get(row["app_id"], {})
        gid = old.get("id", f"steam-{row['app_id']}")
        demo_ids = sorted(set(row.get("demo_app_ids") or []))
        demo = demo_ids[0] if len(demo_ids) == 1 else None
        if old and old["demo_app_id"] != demo:
            raise ValueError("retained_demo_mapping_changed")
        game = {
            "id": gid, "app_id": row["app_id"], "name": row["name"],
            "demo_app_id": demo, "demo_app_ids": demo_ids,
            "store_url": row["store_url"],
            "demo_url": f"https://store.steampowered.com/app/{demo}/" if demo else None,
            "header_image": old.get("header_image") or row.get("header_image"),
            "tags": row.get("tag_names") or [], "genres": row.get("genres") or [],
            "source_status": "ok" if demo else "ambiguous" if len(demo_ids) > 1 else "unresolved",
            "verified_at": stamp(parse(row["verified_at"])),
            "participation": {
                "source_url": source_url, "verified_at": stamp(parse(row["verified_at"])),
                "evidence_excerpt": "공식 2026년 10월 행사 등록 목록에 포함된 AppID입니다.",
            },
        }
        if old:
            game["participation"] = old["participation"]
        games.append(game)
        path = history_path(root, gid)
        if not path.exists():
            hist = blank_history(now)
            for field in ("samples", "events", "analyses"):
                hist[field] = [item for item in initial[field] if item["game_id"] == gid]
            for field in ("news_status", "news_last_attempt_at"):
                if gid in initial.get(field, {}):
                    hist[field][gid] = initial[field][gid]
            save(path, hist)
    generated = stamp(parse(evidence["collection_completed_at"]))
    catalog = {"schema_version": 2, "generated_at": generated,
               "coverage": {"official_total": expected, "unique_total": len(games),
                            "metadata_ok": sum(r["source_status"] == "verified" for r in rows),
                            "complete": True, "scope": "official_event_registration",
                            "source_url": source_url,
                            "region_note": "공식 행사 등록 구성 전체입니다. US·KR 등록 목록은 같지만 국가별 검색 노출·데모 이용 가능 여부는 다릅니다.",
                            "locale": "english", "country_code": "US",
                            "verified_at": generated},
               "games": games}
    config["schema_version"] = 2
    config["collection"].update(
        ccu_request_budget=700, news_request_budget=360, daily_request_budget=90000,
        min_request_interval_seconds=.5, priority_game_ids=[g["id"] for g in config["games"]],
        max_run_seconds=840,
    )
    (root / "config/manifest.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    save(root / "site/data/catalog.json", catalog)
    evidence["normalized_catalog_count"] = len(games)
    evidence["source_catalog_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    save(root / "docs/catalog-evidence.json", evidence)
    state = read_state(root)
    # Conservative allowance for the verified metadata batches and discovery probes.
    state["reservations"].setdefault("catalog-discovery", {
        "day": now.date().isoformat(), "allowance": 200, "used": None,
        "created_at": generated, "completed": True,
        "note": "Discovery reservation; 72 metadata batches plus endpoint probes. Exact probe count not claimed.",
    })
    save(state_path(root), state)
    result = build_indexes(root, config, catalog, now)
    print(result["coverage"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    import_catalog(args.root, args.source, args.evidence)
