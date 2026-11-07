"""Use a local, identity-checked model worker with the existing review contract."""

import hashlib
import json
import os
from pathlib import Path
import socket
import sys

from benchmark_data import digest
from local_review_protocol import review_with_feedback


def verify_files(files):
    for name, expected in files.items():
        if Path(name).name != name:
            raise ValueError("Unsafe runtime source filename")
        actual = hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Frozen model runtime changed: {name}")


def main():
    messages = json.load(sys.stdin)["messages"]
    model = json.loads(Path(os.environ["WEAVE_BATCH_SPEC"]).read_text())["model"]
    expected = os.environ["WEAVE_BATCH_MODEL"]
    if (model["digest"] != expected
            or digest({k: v for k, v in model.items() if k != "digest"}) != expected):
        raise ValueError("Model identity changed")
    verify_files(model["native_batch"]["files"])

    def infer(conversation):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(350)
            connection.connect(os.environ["WEAVE_BATCH_SOCKET"])
            request = {"model_id": expected, "messages": conversation,
                       "schema_messages": messages}
            connection.sendall(json.dumps(request).encode() + b"\n")
            with connection.makefile("r", encoding="utf-8") as stream:
                reply = json.loads(stream.readline())
            if reply.get("model_id") != expected:
                raise ValueError("Local worker model identity changed")
            if reply.get("error"):
                raise ValueError(reply["error"])
            return reply["text"]

    print(json.dumps(review_with_feedback(messages, infer, attempts=3)))


if __name__ == "__main__":
    main()
