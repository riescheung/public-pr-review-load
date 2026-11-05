"""Run the local Devin CLI outside inherited IDE authentication context."""

import os


def cli_environment():
    return {
        key: os.environ[key]
        for key in ("HOME", "USER", "PATH", "TMPDIR", "LANG")
        if key in os.environ
    }
