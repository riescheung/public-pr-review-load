"""Continuously batch local MLX requests with an independent grammar per stream."""

import argparse
import json
import os
from pathlib import Path
import select
import socket
import traceback

from benchmark_data import digest
from mlx_batch_client import verify_files
from mlx_prose_penalty import ProseRepetitionPenalty
from mlx_review_schema import review_schema
from pr_benchmark import installed_mlx_model
from review_artifacts import write_receipt

try:
    import mlx.core as mx
    from mlx_lm import generate
    from mlx_lm.generate import BatchGenerator
    from mlx_lm.sample_utils import make_logits_processors, make_sampler
    from mlx_json_decoder import JSONLogitsProcessor
    from mlx_qwen_loader import load_local_model
except ImportError:
    mx = None


class BatchCoordinator:
    def __init__(self, generator, tokenizer, processor_factory, model_id, max_tokens):
        self.generator = generator
        self.tokenizer = tokenizer
        self.processor_factory = processor_factory
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.active = {}

    def submit(self, request, respond):
        if request["model_id"] != self.model_id:
            raise ValueError("Model identity changed")
        prompt = self.tokenizer.apply_chat_template(
            request["messages"], tokenize=True, add_generation_prompt=True,
            enable_thinking=False,
        )
        processors = self.processor_factory(request["schema_messages"])
        identifier, = self.generator.insert(
            [prompt], max_tokens=[self.max_tokens], logits_processors=[processors],
        )
        self.active[identifier] = (respond, [])
        return identifier

    def step(self):
        _, responses = self.generator.next()
        for response in responses:
            state = self.active.get(response.uid)
            if state is None:
                continue
            respond, tokens = state
            tokens.append(response.token)
            if response.finish_reason is not None:
                del self.active[response.uid]
                respond({"model_id": self.model_id,
                         "text": self.tokenizer.decode(tokens, skip_special_tokens=True)})

    def cancel(self, identifier):
        if identifier in self.active:
            del self.active[identifier]
            self.generator.remove([identifier])


class ScalarCoordinator:
    def __init__(self, infer, model_id):
        self.infer = infer
        self.model_id = model_id
        self.active = {}

    def submit(self, request, respond):
        if request["model_id"] != self.model_id:
            raise ValueError("Model identity changed")
        respond({"model_id": self.model_id, "text": self.infer(request)})

    def cancel(self, identifier):
        pass


def serve(listener, coordinator, raw_dir=None):
    connections = {}

    def finish(connection, payload):
        if raw_dir is not None:
            artifact = {"request": connections[connection].get("request"), "response": payload}
            path = raw_dir / f"{digest(artifact)}.json"
            if not path.exists():
                write_receipt(path, artifact)
        try:
            connection.settimeout(2)
            connection.sendall(json.dumps(payload).encode() + b"\n")
        except OSError:
            pass
        finally:
            connections.pop(connection, None)
            connection.close()

    try:
        while True:
            ready, _, _ = select.select(
                [listener, *connections], [], [], 0 if coordinator.active else 1,
            )
            for connection in ready:
                if connection is listener:
                    while True:
                        try:
                            incoming, _ = listener.accept()
                        except BlockingIOError:
                            break
                        incoming.setblocking(False)
                        connections[incoming] = {"buffer": bytearray(), "uid": None}
                    continue
                state = connections.get(connection)
                if state is None:
                    continue
                data = connection.recv(65536)
                if not data or state["uid"] is not None:
                    coordinator.cancel(state["uid"])
                    connections.pop(connection, None)
                    connection.close()
                    continue
                state["buffer"].extend(data)
                if b"\n" not in state["buffer"]:
                    continue
                try:
                    request = json.loads(state["buffer"].split(b"\n", 1)[0])
                    state["request"] = request
                    state["uid"] = coordinator.submit(
                        request, lambda payload, conn=connection: finish(conn, payload),
                    )
                except Exception as error:
                    traceback.print_exc()
                    finish(connection, {"model_id": coordinator.model_id, "error": str(error)})
            if coordinator.active:
                coordinator.step()
    finally:
        for connection in connections:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    args = parser.parse_args()
    if mx is None:
        raise RuntimeError("The existing local MLX and structured-decoding runtime is required")
    profile = json.loads(args.spec.read_text())["model"]
    if profile["digest"] != digest({k: v for k, v in profile.items() if k != "digest"}):
        raise ValueError("Model identity changed")
    options = profile["native_batch"]
    verify_files(options["files"])
    if installed_mlx_model(args.base, args.adapter) != options["parent_identity"]:
        raise ValueError("Local base, adapter or runtime changed")
    mx.set_memory_limit(options["memory_limit_bytes"])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(args.socket))
        os.chmod(args.socket, 0o600)
        listener.listen(options["batch_size"] + 4)
        listener.setblocking(False)
        model, tokenizer = load_local_model(args.base, adapter_path=args.adapter)
        def processors(messages):
            penalty, = make_logits_processors(
                repetition_penalty=options["repetition_penalty"],
                repetition_context_size=options["repetition_context_size"],
            )
            return [
                ProseRepetitionPenalty(tokenizer, penalty),
                JSONLogitsProcessor(tokenizer, review_schema(messages)),
            ]

        generator = None
        if options["engine"] == "mlx-generate":
            def infer(request):
                prompt = tokenizer.apply_chat_template(
                    request["messages"], tokenize=False, add_generation_prompt=True,
                    enable_thinking=False,
                )
                return generate(
                    model, tokenizer, prompt=prompt, max_tokens=options["max_tokens"],
                    sampler=make_sampler(temp=0),
                    logits_processors=processors(request["schema_messages"]), verbose=False,
                )

            coordinator = ScalarCoordinator(infer, profile["digest"])
        else:
            generator = BatchGenerator(
                model, max_tokens=options["max_tokens"], sampler=make_sampler(temp=0),
                stop_tokens=[[token] for token in tokenizer.eos_token_ids],
                completion_batch_size=options["batch_size"],
                prefill_batch_size=options["prefill_batch_size"],
                prefill_step_size=options["prefill_step_size"],
            )
            coordinator = BatchCoordinator(generator, tokenizer, processors,
                                           profile["digest"], options["max_tokens"])
        try:
            serve(listener, coordinator, args.raw_dir)
        finally:
            if generator is not None:
                generator.close()


if __name__ == "__main__":
    main()
