#!/usr/bin/env python3
"""Manage the Qwen review job through the current user's macOS launchd."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

from review_artifacts import write_bytes
from review_contract import FULL, ROOT


LABEL = "com.riescheung.public-pr-review-load"
LOGS = Path.home() / "Library" / "Logs" / "public-pr-review-load"
AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_agent(manifest, prefix, cohort_size, deploy):
    command = [
        sys.executable, str(ROOT / "scripts" / "continue_mlx_reviews.py"),
        "--manifest", str(manifest.resolve()), "--run-prefix", prefix,
        "--cohort-size", str(cohort_size), "--max-cohorts", "1000", "--execute",
    ]
    if deploy:
        command.append("--deploy")
    return {
        "Label": LABEL, "ProgramArguments": command, "WorkingDirectory": str(ROOT),
        "RunAtLoad": True, "KeepAlive": {"Crashed": True},
        "ThrottleInterval": 60, "ExitTimeOut": 40,
        "StandardOutPath": str(LOGS / "stdout.log"),
        "StandardErrorPath": str(LOGS / "stderr.log"),
        "EnvironmentVariables": {
            "HOME": str(Path.home()), "PATH": os.environ["PATH"],
            "PYTHONPATH": str(FULL / "lora" / "runtime-structured"),
            "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        },
    }


def service_status():
    return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                          capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--prefix", default="qwen-overnight-v1")
    parser.add_argument("--cohort-size", type=int, default=20)
    parser.add_argument("--no-deploy", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This launcher uses macOS user launch agents")
    target = f"gui/{os.getuid()}/{LABEL}"
    if args.action == "stop":
        subprocess.run(["launchctl", "disable", target], check=True)
        result = service_status()
        if result.returncode == 0:
            subprocess.run(["launchctl", "bootout", target], check=True)
        print("Stopped. Saved reviews, logs and resume receipts remain intact.")
        return
    if args.action == "status":
        result = service_status()
        for line in result.stdout.splitlines():
            if re.match(r"\s*(state|pid|last exit code) =", line):
                print(line.strip())
        if result.returncode:
            print("Job is not loaded.")
        path = ROOT / "data" / "contribution_estimates.json"
        if path.exists():
            data = json.loads(path.read_text())
            print(f"Published: {data['overall']['scored']}/{data['overall']['groups']} scored groups")
        if AGENT.exists():
            settings = plistlib.loads(AGENT.read_bytes())["ProgramArguments"]
            prefix = settings[settings.index("--run-prefix") + 1]
            for number in range(1, 1001):
                run = f"{prefix}-{number:04d}"
                spec = ROOT / "data" / "benchmark" / "runs" / run / "spec.json"
                completed = FULL / "harness" / "rollouts" / prefix / f"{number:04d}.json"
                if completed.exists():
                    continue
                if spec.exists():
                    selected = json.loads(spec.read_text())["selected_case_ids"]
                    done = sum((spec.parent / "predictions" / f"{case}.json").exists()
                               for case in selected)
                    print(f"Current cohort: {done}/{len(selected)} saved ({run})")
                break
        print(f"Log: {LOGS / 'stdout.log'}")
        print(f"Errors: {LOGS / 'stderr.log'}")
        return
    if (args.manifest is None or not args.manifest.is_file()
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,54}", args.prefix)
            or not 1 <= args.cohort_size <= 100):
        parser.error("Supply an existing manifest, a safe prefix and a finite cohort size")
    if not shutil.which("node") or not shutil.which("gh"):
        parser.error("Node 22 and the authenticated GitHub CLI must be on PATH")
    major = int(subprocess.check_output(["node", "--version"], text=True).strip()[1:].split(".")[0])
    if major < 22:
        parser.error("Put Node 22 or newer first on PATH before installing the job")
    agent = build_agent(args.manifest, args.prefix, args.cohort_size, not args.no_deploy)
    if AGENT.exists():
        if plistlib.loads(AGENT.read_bytes()) != agent:
            raise ValueError("An existing launch-agent configuration differs; it was not overwritten")
    else:
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(AGENT, plistlib.dumps(agent))
    LOGS.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "enable", target], check=True)
    if service_status().returncode:
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(AGENT)], check=True)
    elif not re.search(r"\bpid = \d+", service_status().stdout):
        subprocess.run(["launchctl", "kickstart", target], check=True)
    print(f"Started independent overnight job: {LABEL}")
    print(f"Log: {LOGS / 'stdout.log'}")
    print("Closing this chat does not stop the launch agent.")


if __name__ == "__main__":
    main()
