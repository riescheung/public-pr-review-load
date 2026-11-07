"""Atomic review receipts and replaceable publication snapshots."""

import json
import os
from pathlib import Path
import tempfile


def write_bytes(path, content, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            if replace:
                temporary.replace(path)
            else:
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def write_receipt(path, body):
    write_bytes(path, (json.dumps(body, indent=2) + "\n").encode())
