"""Bind queue corrections to frozen code and frontier reference predictions."""

import json

from benchmark_data import (
    blind_packet, case_packet, digest, timestamp,
    validate_label, validate_review, write_new,
)
from frontier_reference import reference_records
from pr_benchmark import predictions


def development_cases(manifest):
    reserved = [case["group"] for case in manifest["cases"] if case["split"] != "development"]
    cases = [case for case in manifest["cases"] if case["split"] == "development"]
    for case in cases:
        group = case["group"]
        for other in reserved:
            if (group["id"] == other["id"] or set(group["prs"]) & set(other["prs"])
                    or set(group["diff_sha256"].values()) & set(other["diff_sha256"].values())):
                raise ValueError("Development data overlaps held-out PRs, patches or families")
    return {case["id"]: case for case in cases}


def load_feedback(manifest, directory, references):
    # Event filenames include revisions, unlike one-record-per-case gold labels.
    grouped = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text())
        if (record.get("manifest_sha256") != manifest["sha256"]
                or path.stem != digest(record)):
            raise ValueError("Feedback event provenance changed")
        grouped[path.stem] = record
    cases = development_cases(manifest)
    latest = {}
    for record in sorted(grouped.values(), key=lambda value: value["accepted_at"]):
        identifier = record["case_id"]
        if (identifier not in cases or record.get("source") != "user_feedback"
                or record.get("human_gold") is not False
                or record["reference_sha256"] != digest(references.get(identifier))
                or record["supersedes"] != (digest(latest[identifier]) if identifier in latest else None)
                or record["packet_sha256"] != cases[identifier]["packet_sha256"]):
            raise ValueError("Stale or foreign queue feedback")
        validate_label(record, case_packet(cases[identifier]))
        if record.get("evidence_checked") is not True or "review" not in record:
            raise ValueError("Feedback requires user-checked code evidence")
        latest[identifier] = record
    return latest


def make_queue(manifest, reference_directory, reference_id, run, feedback_directory):
    references = reference_records(manifest, reference_directory)
    corrections = load_feedback(manifest, feedback_directory, references)
    qwen = predictions(manifest, run)
    cases = development_cases(manifest)
    entries = []
    for identifier, reference in references.items():
        if identifier not in cases or reference["status"] != "ok":
            continue
        packet = case_packet(cases[identifier])
        proposed = corrections.get(identifier, reference)
        model_record = qwen.get(identifier)
        qwen_review = model_record.get("review") if model_record else None
        flags = []
        if not model_record or model_record["status"] != "ok":
            flags.append("qwen_unavailable")
        elif qwen_review["score"] != proposed["review"]["score"]:
            flags.append("tier_disagreement")
        if proposed["review"]["score"] == 3:
            flags.append("high_tier")
        if proposed["review"]["score"] is None:
            flags.append("abstention")
        entries.append({
            "case_id": identifier, "packet_sha256": cases[identifier]["packet_sha256"],
            "reference_sha256": digest(reference),
            "supersedes": digest(corrections[identifier]) if identifier in corrections else None,
            "packet": blind_packet(packet), "reference_review": reference["review"],
            "proposed_review": proposed["review"], "qwen_review": qwen_review,
            "flags": flags, "source": proposed["source"],
        })
    body = {
        "version": 1, "manifest_sha256": manifest["sha256"], "reference_id": reference_id,
        "teacher": json.loads((reference_directory / "spec.json").read_text())["teacher"],
        "qwen_run": run, "meaning": "Estimated scope tiers, not measured outcomes",
        "cases": sorted(entries, key=lambda item: (not bool(item["flags"]), item["case_id"])),
    }
    return {**body, "sha256": digest(body)}


def import_feedback(manifest, references, queue, payload, directory):
    body = {key: value for key, value in queue.items() if key != "sha256"}
    if (queue.get("sha256") != digest(body)
            or queue.get("manifest_sha256") != manifest["sha256"]
            or payload.get("queue_sha256") != queue["sha256"]
            or payload.get("version") != 1 or not isinstance(payload.get("answers"), list)):
        raise ValueError("Feedback must match an intact exported queue snapshot")
    cases = development_cases(manifest)
    expected = {item["case_id"]: item for item in queue["cases"]}
    latest = load_feedback(manifest, directory, references)
    pending, seen = [], set()
    for answer in payload["answers"]:
        identifier = answer.get("case_id")
        if identifier not in cases or identifier not in expected or identifier in seen:
            raise ValueError("Feedback contains a reserved, unknown or duplicate case")
        seen.add(identifier)
        case, entry = cases[identifier], expected[identifier]
        parent = digest(latest[identifier]) if identifier in latest else None
        if (answer.get("packet_sha256") != case["packet_sha256"]
                or answer.get("reference_sha256") != digest(references.get(identifier))
                or answer.get("reference_sha256") != entry["reference_sha256"]
                or answer.get("supersedes") != parent):
            raise ValueError("Feedback is stale or refers to different code/reference")
        validate_label(answer, case_packet(case))
        if "review" not in answer or answer.get("evidence_checked") is not True:
            raise ValueError("Training feedback needs a complete, user-checked cited review")
        validate_review(answer["review"], case_packet(case))
        pending.append({
            "manifest_sha256": manifest["sha256"], "case_id": identifier,
            "packet_sha256": case["packet_sha256"],
            "reference_sha256": answer["reference_sha256"], "supersedes": parent,
            "queue_sha256": queue["sha256"], "source": "user_feedback", "human_gold": False,
            "reviewer": answer["reviewer"].strip(), "reason": answer["reason"].strip(),
            "score": answer["score"], "review": answer["review"], "evidence_checked": True,
            "accepted_at": timestamp(),
        })
    for record in pending:
        write_new(directory / f"{digest(record)}.json", record)
    return len(pending)
