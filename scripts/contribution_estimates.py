#!/usr/bin/env python3
"""Publish cited Qwen estimates separately from WPR and measured outcomes."""

import argparse
import json
from pathlib import Path
import re

from benchmark_data import BENCHMARK, digest, load_manifest, timestamp, write_new
from import_ollama_mlx import file_sha256
from pr_benchmark import predictions
from review_contract import FULL, ROOT


PUBLICATION_MANIFESTS = FULL / "harness" / "publication_manifests"


def reserved(group, benchmark):
    for case in benchmark["cases"]:
        other = case["group"]
        if case["split"] == "test" and (
            group["id"] == other["id"] or set(group["prs"]) & set(other["prs"])
            or set(group["diff_sha256"].values()) & set(other["diff_sha256"].values())
        ):
            return True
    return False


def group_key(group):
    return digest({"prs": sorted(group["prs"]), "diff_sha256": group["diff_sha256"]})


def validate_publication(manifest, benchmark, catalog, _catalog_hash, report_hash):
    if (manifest["benchmark_sha256"] != benchmark["sha256"]
            or manifest["report_sha256"] != report_hash):
        raise ValueError("Snapshot or benchmark changed; use a new publication manifest and run")
    # Bind each complete reviewed group, not unrelated cache entries that can grow.
    identifiers = set()
    for case in manifest["cases"]:
        index = case["index"]
        if (not 1 <= index <= len(catalog) or case["group"] != catalog[index - 1]
                or case["source"] != "full" or case["split"] != "publication"
                or case["id"] != "E" + digest(case["group"])[:16]
                or case["id"] in identifiers or reserved(case["group"], benchmark)):
            raise ValueError("Publication contains a reserved, duplicate or foreign case")
        identifiers.add(case["id"])


def archive_publication(manifest):
    if manifest.get("sha256") != digest({k: v for k, v in manifest.items() if k != "sha256"}):
        raise ValueError("Cannot archive a changed publication manifest")
    PUBLICATION_MANIFESTS.mkdir(parents=True, exist_ok=True)
    path = PUBLICATION_MANIFESTS / f"{manifest['sha256']}.json"
    if path.exists():
        if load_manifest(path) != manifest:
            raise ValueError("Publication manifest archive changed")
    else:
        write_new(path, manifest)


def collect_reviews(benchmark, runs, catalog, publication_manifest=None, publication_run=None):
    """Later explicitly selected runs replace earlier ones, including failures."""
    groups = {group_key(group): group["id"] for group in catalog}
    result, models = {}, {}
    sources = [(benchmark, run, "benchmark") for run in runs]
    if publication_manifest and publication_run:
        publication_runs = [publication_run] if isinstance(publication_run, str) else publication_run
        sources.extend((publication_manifest, run, "publication") for run in publication_runs)
    for manifest, run, source in sources:
        spec = json.loads((BENCHMARK / "runs" / run / "spec.json").read_text())
        model = spec["model"]
        if "qwen" not in model["name"].lower():
            raise ValueError("Contribution estimates require an explicitly identified Qwen run")
        models[run] = model
        if source == "publication" and spec.get("manifest_sha256") != manifest.get("sha256"):
            identity = spec["manifest_sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", identity):
                raise ValueError("Invalid publication manifest identity")
            manifest = load_manifest(PUBLICATION_MANIFESTS / f"{identity}.json")
            if manifest["sha256"] != identity:
                raise ValueError("Publication archive does not match its run")
            validate_publication(manifest, benchmark, catalog, None,
                                 publication_manifest["report_sha256"])
        cases = {case["id"]: case for case in manifest["cases"]}
        for identifier, record in predictions(manifest, run).items():
            case = cases[identifier]
            key = group_key(case["group"])
            if case["split"] == "test" or reserved(case["group"], benchmark) or key not in groups:
                continue
            review = record.get("review")
            status = record["status"]
            if status == "ok" and (review["score"] is None or review["grouping_issue"]):
                status = "abstained"
            result[groups[key]] = {
                "id": groups[key], "prs": sorted(case["group"]["prs"]),
                "status": status, "tier": review["score"] if status == "ok" else None,
                "review": review, "run": run, "source": source,
                "known_calibration": case["split"] == "calibration",
                "packet_sha256": case["packet_sha256"],
                "prediction_sha256": digest(record),
            }
    return result, models


def empty_summary():
    return {
        "groups": 0, "scored": 0, "abstained": 0, "failed": 0, "reserved": 0,
        "pending": 0, "mean_tier": None, "tiers": {"1": 0, "2": 0, "3": 0},
        "review_ids": [], "unmapped_prs": 0,
    }


def add_group(summary, group, record, held_out):
    summary["groups"] += 1
    if held_out:
        summary["reserved"] += 1
    elif record:
        summary["review_ids"].append(group["id"])
        if record["status"] == "ok":
            summary["scored"] += 1
            summary["tiers"][str(record["tier"])] += 1
        elif record["status"] == "abstained":
            summary["abstained"] += 1
        else:
            summary["failed"] += 1
    else:
        summary["pending"] += 1
    if summary["scored"]:
        summary["mean_tier"] = sum(int(tier) * n for tier, n in summary["tiers"].items()) / summary["scored"]


def aggregate(report, catalog, records, benchmark):
    """Count a group once per associated author, in their latest member-PR interval."""
    people = {person["login"]: {
        "periods": [empty_summary() for _ in report["periods"]], "total": empty_summary(),
    } for person in report["people"]}
    locations = {}
    for person in report["people"]:
        for index, period in enumerate(person["periods"]):
            for pr in period["prs"]:
                if pr["number"] in locations:
                    raise ValueError("Snapshot assigns a PR to more than one author/period")
                locations[pr["number"]] = (person["login"], index)
    seen_prs, seen_groups = set(), set()
    overall = empty_summary()
    for group in catalog:
        if group["id"] in seen_groups or seen_prs.intersection(group["prs"]):
            raise ValueError("Catalog repeats a group or PR; refusing duplicate contribution credit")
        seen_groups.add(group["id"])
        seen_prs.update(group["prs"])
        owners = {}
        for number in group["prs"]:
            if number in locations:
                login, index = locations[number]
                owners[login] = max(owners.get(login, -1), index)
        held_out = reserved(group, benchmark)
        record = records.get(group["id"])
        if held_out and record:
            raise ValueError("Reserved test reviews cannot be published")
        if record and (record["prs"] != sorted(group["prs"])
                       or record["status"] == "ok" and type(record["tier"]) is not int
                       or record["status"] == "ok" and record["tier"] not in (1, 2, 3)):
            raise ValueError("Review is not bound to this complete group")
        if owners:
            add_group(overall, group, record, held_out)
        for login, index in owners.items():
            add_group(people[login]["periods"][index], group, record, held_out)
            add_group(people[login]["total"], group, record, held_out)
    for number in set(locations) - seen_prs:
        login, index = locations[number]
        people[login]["periods"][index]["unmapped_prs"] += 1
        people[login]["total"]["unmapped_prs"] += 1
        overall["unmapped_prs"] += 1
    return people, overall


def publish(benchmark, runs, destination, publication_manifest=None, publication_run=None):
    if destination.exists() and not publication_manifest:
        old = json.loads(destination.read_text())
        if any(row["source"] == "publication" for row in old.get("reviews", {}).values()):
            raise ValueError("Preserve expanded coverage: supply its publication manifest and run")
    report_path, catalog_path = ROOT / "data" / "report.json", FULL / "selection.json"
    report, catalog = json.loads(report_path.read_text()), json.loads(catalog_path.read_text())
    if publication_manifest:
        validate_publication(publication_manifest, benchmark, catalog,
                             file_sha256(catalog_path), file_sha256(report_path))
        archive_publication(publication_manifest)
    records, models = collect_reviews(benchmark, runs, catalog, publication_manifest, publication_run)
    people, overall = aggregate(report, catalog, records, benchmark)
    body = {
        "version": 1, "generated_at": timestamp(), "label": "AI-estimated contribution",
        "meaning": "Mean 1-3 scope tier among scored change groups; not measured outcomes or individual performance",
        "aggregation": "One group per contributor, assigned to the latest interval containing that contributor's member PR",
        "human_gold": False, "report_sha256": file_sha256(report_path),
        "catalog_sha256": file_sha256(catalog_path), "benchmark_sha256": benchmark["sha256"],
        "models": models, "overall": overall, "people": people, "reviews": records,
    }
    # This file is a generated publication, not an immutable experiment receipt.
    destination.write_text(json.dumps({**body, "sha256": digest(body)}, indent=2) + "\n")
    print(f"Published {overall['scored']}/{overall['groups']} scored change groups; "
          f"{overall['reserved']} reserved groups remain excluded.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-run", action="append",
                        help="Explicit Qwen run; repeat in replacement priority order")
    parser.add_argument("--publication-manifest", type=Path)
    parser.add_argument("--publication-run", action="append")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "contribution_estimates.json")
    args = parser.parse_args()
    runs = args.benchmark_run or ["qwen-base-v2", "mlx-distilled-v4"]
    if bool(args.publication_manifest) != bool(args.publication_run):
        parser.error("Supply both publication manifest and run")
    for name in runs + (args.publication_run or []):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            parser.error("Use safe, explicit run names")
    publication = load_manifest(args.publication_manifest) if args.publication_manifest else None
    publish(load_manifest(), runs, args.output, publication, args.publication_run)


if __name__ == "__main__":
    main()
