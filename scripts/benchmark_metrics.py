"""Honest selective-classification metrics; syntax is not semantic evidence."""


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def metrics(cases, runs, labels, audits):
    ids = [c["id"] for c in cases]
    labelled = [i for i in ids if i in labels]
    model = [i for i in labelled if runs.get(i, {}).get("status") in ("ok", "error")]
    ok = [i for i in model if runs[i]["status"] == "ok"]
    predictions = {i: runs[i]["review"]["score"] for i in ok}
    assessed = [i for i in ok if predictions[i] is not None]
    tiers = {}
    for tier in (1, 2, 3):
        tp = sum(predictions.get(i) == tier and labels[i]["score"] == tier for i in ok)
        predicted = sum(predictions[i] == tier for i in ok)
        support = sum(labels[i]["score"] == tier for i in model)
        precision, recall = ratio(tp, predicted), ratio(tp, support)
        f1 = 2 * tp / (predicted + support) if predicted + support else None
        tiers[str(tier)] = {
            "support": support, "predicted": predicted, "true_positives": tp,
            "precision": precision, "recall": recall, "f1": f1,
        }
    abstained = [i for i in ok if predictions[i] is None]
    semantic = [audits[i]["verdict"] for i in ids if i in audits]
    decisive_audits = [v for v in semantic if v in ("correct", "incorrect")]
    return {
        "cases": len(ids), "labelled": len(labelled), "unlabelled": len(ids) - len(labelled),
        "completed": sum(runs.get(i, {}).get("status") == "ok" for i in ids),
        "errors": sum(runs.get(i, {}).get("status") == "error" for i in ids),
        "deferred": sum(runs.get(i, {}).get("status") == "deferred" for i in ids),
        "not_run": sum(i not in runs for i in ids),
        "preflight_rejections": sum(runs.get(i, {}).get("status") == "preflight" for i in ids),
        "model_labelled_attempts": len(model),
        "model_exact_accuracy": ratio(sum(predictions[i] == labels[i]["score"] for i in ok), len(model)),
        "selective_accuracy": ratio(sum(predictions[i] == labels[i]["score"] for i in assessed), len(assessed)),
        "coverage": ratio(len(assessed), len(model)),
        "per_tier": tiers,
        "macro_f1": (sum(t["f1"] or 0 for t in tiers.values()) / 3) if model else None,
        "tier3": {
            "precision": tiers["3"]["precision"],
            "false_positives": sum(predictions[i] == 3 and labels[i]["score"] != 3 for i in ok),
        },
        "abstention_precision": ratio(sum(labels[i]["score"] is None for i in abstained), len(abstained)),
        "abstention_recall": ratio(sum(labels[i]["score"] is None for i in abstained),
                                   sum(labels[i]["score"] is None for i in model)),
        "semantic_audited": len(semantic),
        "semantic_unclear": semantic.count("unclear"),
        "semantic_evidence_accuracy": ratio(decisive_audits.count("correct"), len(decisive_audits)),
        "promotion": "Not automatic: require a paired held-out comparison and human approval",
    }


def compare(baseline, candidate):
    if baseline["split"] != "test" or candidate["split"] != "test":
        raise ValueError("Promotion requires locked test results, not development/calibration")
    if (baseline["manifest_sha256"] != candidate["manifest_sha256"]
            or baseline["case_ids"] != candidate["case_ids"]):
        raise ValueError("Comparison must be paired on the same frozen cases")
    blockers = []
    if candidate.get("experimental_ai_labels"):
        blockers.append("This isolated AI-distillation experiment is not eligible for promotion")
    if (not baseline.get("harness_sha256")
            or baseline.get("harness_sha256") != candidate.get("harness_sha256")):
        blockers.append("Both test runs must pin the same harness implementation")
    for field in ("base_model_sha256", "evaluation_protocol_sha256"):
        if not baseline.get(field) or baseline.get(field) != candidate.get(field):
            blockers.append(f"Both test runs must pin the same {field}")
    for name, report in (("baseline", baseline), ("candidate", candidate)):
        if (report["labelled"] < 50 or report["unlabelled"]
                or report["not_run"] or report["errors"] or report["deferred"]):
            blockers.append(f"{name}: need >=50 fully labelled cases and complete error-free runs")
        if (report["semantic_audited"] != report["completed"]
                or report["semantic_unclear"]
                or report["semantic_evidence_accuracy"] is None):
            blockers.append(f"{name}: independent semantic audits are incomplete")
    if (candidate["per_tier"]["3"]["support"] < 10
            or candidate["per_tier"]["3"]["predicted"] < 10
            or (candidate["tier3"]["precision"] or 0) < 0.9):
        blockers.append("candidate: need >=10 true tier-3 cases, >=10 predictions and >=90% precision")
    for metric in ("model_exact_accuracy", "coverage", "semantic_evidence_accuracy"):
        if (candidate[metric] is None or baseline[metric] is None
                or candidate[metric] < baseline[metric]):
            blockers.append(f"candidate: {metric} regresses or is unmeasured")
    if candidate["semantic_evidence_accuracy"] is None or candidate["semantic_evidence_accuracy"] < 0.95:
        blockers.append("candidate: semantic evidence accuracy must reach 95%")
    if (baseline["tier3"]["precision"] is not None
            and (candidate["tier3"]["precision"] or 0) < baseline["tier3"]["precision"]):
        blockers.append("candidate: tier-3 precision regresses")
    if (candidate["macro_f1"] is None or baseline["macro_f1"] is None
            or candidate["macro_f1"] <= baseline["macro_f1"]):
        blockers.append("candidate: macro-F1 must improve over the paired baseline")
    return {
        "eligible_for_human_approval": not blockers, "blockers": blockers,
        "promoted": False,
        "note": "Provisional experiment gates, not proof of generalization; human approval is still required",
    }
