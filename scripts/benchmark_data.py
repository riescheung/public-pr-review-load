"""Frozen benchmark selection, blind packets and human-label validation."""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json

from review_contract import FULL, PILOT, REPOSITORY, ROOT, review_instructions
from score_harness import make_packet, validate_decision, validate_observations


BENCHMARK = ROOT / "data" / "benchmark"
MANIFEST = BENCHMARK / "manifest.json"
SEED = "posthog-benchmark-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seal(value):
    return {**value, "sha256": digest(value)}


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as output:
        output.write(json.dumps(value, indent=2) + "\n")


def load_manifest(path=MANIFEST):
    manifest = json.loads(path.read_text())
    body = {k: v for k, v in manifest.items() if k != "sha256"}
    if manifest.get("sha256") != digest(body):
        raise ValueError("Benchmark manifest changed; do not reuse existing runs or labels")
    return manifest


def blind_packet(packet):
    return {key: packet[key] for key in ("system", "chunks", "abstention_reason")}


def select_cases(candidates, count):
    """Round-robin cached strata, excluding shared PRs and identical patches."""
    buckets = defaultdict(list)
    for candidate in sorted(candidates, key=lambda c: digest([SEED, c["group"]])):
        buckets[candidate["stratum"]].append(candidate)
    chosen, prs, hashes = [], set(), set()
    while buckets and len(chosen) < count:
        for key in sorted(list(buckets)):
            candidate = buckets[key].pop(0)
            group = candidate["group"]
            fingerprints = set(group["diff_sha256"].values())
            if not prs.intersection(group["prs"]) and not hashes.intersection(fingerprints):
                chosen.append(candidate)
                prs.update(group["prs"])
                hashes.update(fingerprints)
            if not buckets[key]:
                del buckets[key]
            if len(chosen) == count:
                break
    if len(chosen) != count:
        raise ValueError(f"Only {len(chosen)} disjoint cached cases; requested {count}")
    return chosen


def case_packet(case):
    source = FULL if case["source"] == "full" else PILOT
    packet = make_packet(case["group"], source / "diffs")
    if digest(packet) != case["packet_sha256"]:
        raise ValueError(f"Stale or unavailable packet for {case['id']}")
    return packet


def export_packets(manifest, destination=BENCHMARK):
    assignments = defaultdict(list)
    for case in manifest["cases"]:
        packet = case_packet(case)
        blind = blind_packet(packet)
        assignments[case["split"]].append(case["id"])
        documents = {
            f"{case['id']}.json": json.dumps(blind, indent=2) + "\n",
        }
        markdown = [
            f"# Blind change {case['id']}", packet["system"],
            f"Evidence preflight: {packet['abstention_reason'] or 'complete reviewable hunks'}",
        ]
        for index, chunk in enumerate(packet["chunks"], 1):
            fence = "`" * max(4, max((len(s) + 1 for s in chunk["text"].split()
                                      if s and set(s) == {"`"}), default=4))
            markdown.append(
                f"## Chunk {index} of {len(packet['chunks'])}\n\n"
                f"{fence}diff\n{chunk['text']}\n{fence}"
            )
        documents[f"{case['id']}.md"] = "\n\n".join(markdown) + "\n"
        for filename, text in documents.items():
            path = destination / "packets" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_text() != text:
                    raise ValueError(f"Existing blind packet differs: {path}")
            else:
                with path.open("x") as output:
                    output.write(text)
    for split, identifiers in assignments.items():
        path = destination / "packets" / f"{split}.json"
        if path.exists():
            if json.loads(path.read_text()) != identifiers:
                raise ValueError("Blind assignment list changed")
        else:
            write_new(path, identifiers)


def prepare(count=100, development=40, destination=BENCHMARK):
    if not 0 < development < count:
        raise ValueError("Reserve both development and test cases")
    manifest_path = destination / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError("Benchmark already frozen; use its existing manifest")
    pilot = json.loads((PILOT / "selection.json").read_text())
    teachers = json.loads((FULL / "teacher_labels.json").read_text())
    catalog = json.loads((FULL / "selection.json").read_text())
    old_prs = {pr for group in pilot for pr in group["prs"]}
    old_hashes = {h for group in pilot for h in group["diff_sha256"].values()}
    for label in teachers:
        group = catalog[label["index"] - 1]
        old_prs.update(group["prs"])
        old_hashes.update(group["diff_sha256"].values())
    candidates = []
    for index, group in enumerate(catalog, 1):
        if (not group["diff_sha256"] or old_prs.intersection(group["prs"])
                or old_hashes.intersection(group["diff_sha256"].values())):
            continue
        packet = make_packet(group, FULL / "diffs")
        # Missing local files are not a meaningful model benchmark.
        if packet["abstention_reason"] and "Missing cached" in packet["abstention_reason"]:
            continue
        paths = [
            part.split(" path=", 1)[1].split(">", 1)[0].strip('"')
            for chunk in packet["chunks"]
            for part in chunk["text"].split("<hunk id=")[1:]
        ]
        area = paths[0].split("/")[0] if paths else "unreadable"
        kind = ("preflight" if packet["abstention_reason"] else
                "multi_pr" if len(group["prs"]) > 1 else
                "large" if len(packet["chunks"]) > 1 else "single")
        candidates.append({
            "group": {k: group[k] for k in ("id", "prs", "diff_sha256")},
            "source": "full", "index": index, "stratum": f"{kind}/{area}",
            "packet_sha256": digest(packet),
        })
    selected = select_cases(candidates, count)
    for index, case in enumerate(selected):
        case["split"] = "development" if index < development else "test"
    calibrations = json.loads((PILOT / "calibration.json").read_text())
    for label in calibrations:
        group = pilot[label["index"] - 1]
        packet = make_packet(group, PILOT / "diffs")
        if (packet["instructions_sha256"] != label["instructions_sha256"]
                or packet["diff_sha256"] != label["diff_sha256"]):
            raise ValueError("Historical calibration no longer matches")
        selected.append({
            "group": {k: group[k] for k in ("id", "prs", "diff_sha256")},
            "source": "pilot", "index": label["index"], "stratum": "historical",
            "packet_sha256": digest(packet), "split": "calibration",
        })
    for case in selected:
        case["id"] = "C" + digest(case["group"])[:12]
    manifest = seal({
        "version": 1, "repository": REPOSITORY, "seed": SEED,
        "instructions_sha256": review_instructions()[1],
        "population": "Diversity sample of locally cached diffs, not a population estimate",
        "cases": selected,
    })
    write_new(manifest_path, manifest)
    export_packets(manifest, destination)
    for label, case in zip(calibrations, selected[count:]):
        write_new(destination / "labels" / f"{case['id']}.json", {
            "manifest_sha256": manifest["sha256"], "case_id": case["id"],
            "score": label["human_score"], "reason": label["reason"],
            "reviewer": label["reviewer"], "source": "historical_human_calibration",
        })
    return manifest


def validate_review(review, packet):
    if not isinstance(review, dict):
        raise ValueError("Approved review must be an object")
    if packet["abstention_reason"]:
        if review.get("score") is not None:
            raise ValueError("Cannot score unavailable code evidence")
        validate_decision(review, set())
        if review.get("observations") != []:
            raise ValueError("Unavailable evidence cannot have observations")
        return
    observations = review.get("observations")
    if not isinstance(observations, list) or len(observations) != len(packet["chunks"]):
        raise ValueError("One approved observation set is required for every chunk")
    ids = set()
    for reply, chunk in zip(observations, packet["chunks"]):
        validate_observations(reply, chunk["changed_lines"])
        ids.update(item["hunk"] for item in reply["observations"])
    validate_decision(review, ids)


def validate_label(answer, packet):
    if not isinstance(answer, dict):
        raise ValueError("Human answer must be an object")
    score = answer.get("score")
    if "score" not in answer or (type(score) is not int and score is not None) or score not in (1, 2, 3, None):
        raise ValueError("Human score must be 1, 2, 3 or null")
    for key in ("reviewer", "reason"):
        if not isinstance(answer.get(key), str) or len(answer[key].strip()) < (2 if key == "reviewer" else 15):
            raise ValueError(f"Human {key} is required")
    if packet["abstention_reason"] and score is not None:
        raise ValueError("Cannot assign a tier to unavailable code")
    if "review" in answer:
        validate_review(answer["review"], packet)
        if answer["review"]["score"] != score:
            raise ValueError("Label and approved review disagree")
    return answer


def validate_audit(answer):
    if (not isinstance(answer, dict)
            or answer.get("verdict") not in ("correct", "incorrect", "unclear")):
        raise ValueError("Semantic evidence audit needs correct, incorrect or unclear")
    for key, minimum in (("reviewer", 2), ("reason", 15)):
        if not isinstance(answer.get(key), str) or len(answer[key].strip()) < minimum:
            raise ValueError(f"Semantic evidence audit needs a specific {key}")


def load_records(directory, manifest):
    records = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text())
        if (record.get("manifest_sha256") != manifest["sha256"]
                or record.get("case_id") != path.stem
                or path.stem not in {c["id"] for c in manifest["cases"]}):
            raise ValueError(f"Stale or foreign record: {path}")
        records[path.stem] = record
    return records


def timestamp():
    return datetime.now(timezone.utc).isoformat()
