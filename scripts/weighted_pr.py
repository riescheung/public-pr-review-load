"""Estimated review load based on the supplied weighted-PR rubric.

This estimates review load, not impact. The report uses it only as a capped
scope proxy alongside a separate, provisional work-type rubric.
"""

import math
from pathlib import PurePosixPath
import re


DENSITY = {
    ".py": (0.85, 0.92), ".rb": (0.85, 0.92),
    ".go": (0.80, 0.90), ".sql": (0.80, 0.90),
    ".js": (0.70, 0.85), ".jsx": (0.70, 0.85),
    ".ts": (0.65, 0.80), ".tsx": (0.65, 0.80),
    ".java": (0.55, 0.75), ".html": (0.50, 0.65),
    ".json": (0.50, 0.50), ".yaml": (0.60, 0.60),
    ".yml": (0.60, 0.60), ".md": (0.35, 0.35),
    ".css": (0.50, 0.65), ".scss": (0.50, 0.65),
}
TYPE_WEIGHT = {
    "CODE": 1.0, "TEST": 0.6, "STYLE": 0.3,
    "TEMPLATE": 0.25, "CONFIG": 0.25, "DATA": 0.15,
    "DOC": 0.1, "ASSET": 0.0, "GENERATED": 0.0,
}
CONFIG_NAMES = {
    "Dockerfile", "Makefile", "Jenkinsfile", "Vagrantfile",
}


def classify(path):
    lower = path.lower()
    name = PurePosixPath(path).name
    suffix = PurePosixPath(lower).suffix
    parts = lower.split("/")
    if (
        any(part in {"generated", "__generated__", "fixtures", "test_data"}
            for part in parts)
        or lower.endswith((".lock", ".tfstate", ".tfstate.backup", ".age",
                           ".gpg", ".enc", ".sops", ".cdx.json"))
        or name in {"package-lock.json", "go.sum"}
        or re.search(r"(?:^|/)(?:sbom[^/]*|sealed-[^/]*)\.(?:json|yaml)$", lower)
    ):
        return "GENERATED", (0.0, 0.0)
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff",
                  ".woff2", ".ico", ".pdf", ".mp4", ".mov"}:
        return "ASSET", (0.05, 0.05)
    if suffix in {".md", ".mdx", ".txt", ".rst"}:
        return "DOC", DENSITY.get(suffix, (0.35, 0.35))
    if re.search(r"(?:^|/)(?:test_|tests?/|spec/|__tests__/)", lower):
        if suffix in {".py", ".rb", ".go", ".js", ".jsx", ".ts", ".tsx"}:
            return "TEST", DENSITY.get(suffix, (0.65, 0.75))
    if suffix in {".css", ".scss", ".sass", ".less"}:
        return "STYLE", DENSITY.get(suffix, (0.5, 0.65))
    if suffix in {".html", ".jinja", ".j2", ".hbs"}:
        return "TEMPLATE", DENSITY.get(suffix, (0.5, 0.65))
    if name in CONFIG_NAMES or suffix in {".toml", ".tf", ".hcl", ".cue",
                                           ".dhall", ".rego", ".lkml"}:
        return "CONFIG", (0.6, 0.75)
    if suffix in {".yaml", ".yml"}:
        if re.search(r"(?:^|/)(?:\\.buildkite/|\\.github/|helm/|k8s/)", lower):
            return "CONFIG", (0.55, 0.65)
        return "DATA", DENSITY[suffix]
    if suffix == ".json":
        return "DATA", DENSITY[suffix]
    if suffix in {".csv", ".tsv", ".parquet", ".avro"}:
        return "ASSET", (0.0, 0.0)
    if suffix in DENSITY:
        return "CODE", DENSITY[suffix]
    return "CODE", (0.65, 0.8)


def is_net_revert(title):
    return title.startswith("Revert ") and title.count("Revert") % 2 == 1


def weighted_pr(files, title):
    if is_net_revert(title):
        return 0
    classified = [(entry, *classify(entry["path"])) for entry in files]
    meaningful = [
        kind for _, kind, _ in classified
        if kind not in {"DOC", "ASSET", "GENERATED"}
    ]
    config_only = bool(meaningful) and (
        sum(kind in {"CONFIG", "DATA"} for kind in meaningful)
        / len(meaningful) >= 0.75
    )
    adjusted = []
    for entry, kind, densities in classified:
        changes = entry["additions"] + entry["deletions"]
        change = entry["changeType"]
        if kind in {"ASSET", "GENERATED"} or (
            change == "RENAMED" and changes == 0
        ):
            continue
        density = densities[0 if change == "ADDED" else 1]
        weight = 1.0 if config_only and kind in {"CONFIG", "DATA"} else (
            TYPE_WEIGHT[kind]
        )
        change_weight = (
            0.8 if change == "ADDED" else 0.1 if change in {"DELETED", "REMOVED"}
            else 1.0
        )
        score = changes * density * weight * change_weight
        if score >= 2.0:
            adjusted.append(score)
    if not adjusted:
        return 0
    factor = 1 + 0.25 * (1 - math.exp(-len(adjusted) / 10))
    raw = 1 + sum(adjusted) * factor / 104.4
    return max(1, min(10, math.floor(raw + 0.5)))
