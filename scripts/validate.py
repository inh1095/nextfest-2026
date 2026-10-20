#!/usr/bin/env python3
"""Validate public dataset and causal-analysis references before publication."""
from pathlib import Path
from urllib.parse import urlsplit
from collect import ROOT, load_json, parse


def require(condition, message):
    if not condition:
        raise ValueError(message)


def url(value):
    require(isinstance(value, str) and urlsplit(value).scheme == "https", "https_source_required")
    require(not urlsplit(value).username and not urlsplit(value).password, "credential_in_url")


def validate(root: Path = ROOT):
    config = load_json(root / "config/manifest.json")
    public = load_json(root / "site/data/config.json")
    data = load_json(root / "site/data/observations.json")
    require(config == public, "public_config_mismatch")
    require(config["schema_version"] == data["schema_version"] == 1, "schema_version")
    start, stop = parse(config["event"]["starts_at"]), parse(config["collection"]["stops_at"])
    require(start < stop, "collection_window")
    require(stop == parse(config["event"]["ends_at"]), "unexpected_post_event_collection")
    require(len(config["games"]) == 2, "expected_two_games")
    game_ids = {game["id"] for game in config["games"]}
    require(len(game_ids) == 2, "duplicate_game")
    for game in config["games"]:
        require(isinstance(game["app_id"], int) and isinstance(game["demo_app_id"], int), "appid_type")
        require(game["app_id"] != game["demo_app_id"], "base_demo_confusion")
        url(game["participation"]["source_url"])
        require(bool(game["participation"]["evidence_excerpt"]), "participation_evidence_missing")
        for metric in game["metrics"]:
            url(metric["source_url"])
            require(metric["key"] in {"demo_ccu", "followers"}, "unknown_metric")
            if metric["availability"] != "available":
                require(bool(metric.get("unavailable_reason")), "missing_unavailable_reason")
    seen = set()
    for sample in data["samples"]:
        require(sample["game_id"] in game_ids, "unknown_sample_game")
        require(sample["metric"] in {"demo_ccu", "followers"}, "unknown_sample_metric")
        at = parse(sample["observed_at"])
        require(start <= at < stop, "sample_outside_observation_window")
        key = (sample["game_id"], sample["metric"], sample["observed_at"])
        require(key not in seen, "duplicate_sample")
        seen.add(key)
        url(sample["source_url"])
        if sample["status"] == "ok":
            require(type(sample["value"]) is int and sample["value"] >= 0, "invalid_measurement")
            if sample["metric"] == "followers":
                raise ValueError("followers_not_verified_for_this_project")
        else:
            require(sample["status"] in {"error", "unavailable"}, "unknown_sample_status")
            require(sample["value"] is None, "missing_value_must_be_null")
    event_ids = set()
    for event in data["events"]:
        require(event["id"] not in event_ids, "duplicate_event")
        event_ids.add(event["id"])
        require(event["game_id"] in game_ids, "unknown_event_game")
        url(event["source_url"])
        for key in ("occurred_at", "published_at"):
            if event.get(key):
                parse(event[key])
        parse(event["verified_at"])
    for analysis in data["analyses"]:
        require(analysis["game_id"] in game_ids, "unknown_analysis_game")
        require(set(analysis["evidence_event_ids"]).issubset(event_ids), "analysis_evidence_missing")
        require(analysis["assessment"] in {"direct_evidence", "temporal_association", "insufficient"}, "invalid_assessment")
        begins, ends, reviewed = parse(analysis["from"]), parse(analysis["to"]), parse(analysis["reviewed_at"])
        require(start <= begins <= ends < stop and ends <= reviewed, "invalid_analysis_window")
        samples = {
            s["observed_at"]: s for s in data["samples"]
            if s["game_id"] == analysis["game_id"] and s["status"] == "ok"
        }
        require(bool(analysis["evidence_sample_times"]), "analysis_sample_evidence_missing")
        for at in analysis["evidence_sample_times"]:
            require(at in samples and begins <= parse(at) <= ends, "invalid_analysis_sample_reference")
        for event in data["events"]:
            if event["id"] in analysis["evidence_event_ids"]:
                require(event["game_id"] == analysis["game_id"], "analysis_event_wrong_game")
    require(data["collection_status"] in {"pending", "active", "archived"}, "collection_status")
    print(f"Validated {len(config['games'])} games, {len(data['samples'])} observations, {len(data['events'])} events.")


if __name__ == "__main__":
    validate()
