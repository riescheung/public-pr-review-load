#!/usr/bin/env python3
"""Split web evidence into immutable assets without changing any review."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from benchmark_data import digest
from review_artifacts import write_bytes
from review_contract import ROOT


INDEX_FIELDS = ("id", "prs", "status", "tier", "run", "source", "known_calibration")
ASSET_FORMAT = "sha256-json-v1"


def read_evidence(entry, directory):
    expected = entry.get("evidence_sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid evidence filename")
    raw = (directory / f"{expected}.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Review evidence hash mismatch")
    record = json.loads(raw)
    if (set(entry) != {*INDEX_FIELDS, "evidence_sha256"}
            or any(record[field] != entry[field] for field in INDEX_FIELDS)):
        raise ValueError("Review evidence does not match its index")
    return record


def prepare_assets(path, directory):
    publication = json.loads(path.read_bytes())
    body = {key: value for key, value in publication.items() if key != "sha256"}
    if digest(body) != publication.get("sha256"):
        raise ValueError("Publication hash mismatch; refusing evidence conversion")
    if body["version"] == 2:
        if body.get("evidence_storage") != ASSET_FORMAT:
            raise ValueError("Unsupported evidence storage format")
        original = {key: value for key, value in body.items()
                    if key not in ("evidence_storage", "inline_publication_sha256")}
        original["version"] = 1
        original["reviews"] = {
            identifier: read_evidence(entry, directory)
            for identifier, entry in body["reviews"].items()
        }
        if digest(original) != body["inline_publication_sha256"]:
            raise ValueError("Review evidence does not reconstruct its original publication")
        return
    if body["version"] != 1:
        raise ValueError("Unsupported publication version")
    entries = {}
    for identifier, record in body["reviews"].items():
        raw = json.dumps(record, separators=(",", ":")).encode()
        identity = hashlib.sha256(raw).hexdigest()
        destination = directory / f"{identity}.json"
        if destination.exists():
            if destination.read_bytes() != raw:
                raise ValueError("Existing review evidence changed")
        else:
            write_bytes(destination, raw)
        entries[identifier] = {
            **{key: record[key] for key in INDEX_FIELDS}, "evidence_sha256": identity,
        }
    body.update(version=2, reviews=entries, evidence_storage=ASSET_FORMAT,
                inline_publication_sha256=publication["sha256"])
    content = json.dumps({**body, "sha256": digest(body)}, indent=2) + "\n"
    write_bytes(path, content.encode(), replace=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=ROOT / "data" / "contribution_estimates.json")
    parser.add_argument("--directory", type=Path,
                        default=ROOT / "public" / "review-evidence")
    args = parser.parse_args()
    prepare_assets(args.input, args.directory)


if __name__ == "__main__":
    main()
