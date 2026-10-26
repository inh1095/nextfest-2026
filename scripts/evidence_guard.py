#!/usr/bin/env python3
"""Reject removal or changes to previously committed evidence before publishing."""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from collect import ROOT

EVIDENCE_FIELDS = ("samples", "events", "analyses", "disclosures", "follower_checks", "methods")


def signature(record):
    return json.dumps(record, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def require_preserved(before, after, path):
    count = 0
    fields = EVIDENCE_FIELDS + (('games', 'sources') if str(path) == 'config/game-context.json' else ())
    for field in fields:
        previous = Counter(map(signature, before.get(field, [])))
        current = Counter(map(signature, after.get(field, [])))
        if previous - current:
            raise ValueError(f"evidence_changed_or_removed: {path}: {field}")
        count += sum(previous.values())
    return count


def check_evidence(root: Path = ROOT, baseline_ref: str = "HEAD"):
    def git(*args, **kwargs):
        return subprocess.run(["git", *args], cwd=root, check=True,
                              stdout=subprocess.PIPE, **kwargs).stdout

    revision = git("rev-parse", "--verify", "--end-of-options",
                   f"{baseline_ref}^{{commit}}").decode().strip()
    paths = git("ls-tree", "-r", "-z", "--name-only", revision, "--",
                "site/data/games/", "site/data/observations.json",
                "config/wishlist-evidence.json", "site/data/wishlists.json",
                "config/game-context.json").decode().split("\0")
    paths = [p for p in paths if p.endswith(".json")]
    if not paths:
        raise ValueError("baseline_has_no_evidence")
    requests = "".join(f"{revision}:{path}\n" for path in paths).encode()
    blobs = git("cat-file", "--batch", input=requests)
    offset, records = 0, 0
    for path in paths:
        line_end = blobs.index(b"\n", offset)
        header = blobs[offset:line_end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError(f"baseline_evidence_unreadable: {path}")
        size = int(header[2])
        offset = line_end + 1
        before = json.loads(blobs[offset:offset + size])
        offset += size + 1
        current_path = root / path
        if not current_path.is_file() or current_path.is_symlink():
            raise ValueError(f"evidence_file_removed_or_replaced: {path}")
        after = json.loads(current_path.read_text())
        records += require_preserved(before, after, path)
    result = {"baseline": revision, "files": len(paths), "preserved_records": records}
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    args = parser.parse_args()
    check_evidence(baseline_ref=args.baseline_ref)
