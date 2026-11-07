import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mlx_batch_server import BatchCoordinator, ScalarCoordinator


class Tokenizer:
    def apply_chat_template(self, messages, **kwargs):
        return [ord(messages[-1]["content"])]

    def decode(self, tokens, **kwargs):
        return "".join(chr(token) for token in tokens if token)


class Generator:
    def __init__(self):
        self.inserted = []
        self.responses = []
        self.removed = []

    def insert(self, prompts, **kwargs):
        self.inserted.append((prompts, kwargs))
        return [len(self.inserted)]

    def next(self):
        return [], self.responses.pop(0)

    def remove(self, identifiers):
        self.removed.extend(identifiers)


def request(text, model="model"):
    return {"model_id": model, "messages": [{"content": text}],
            "schema_messages": [{"content": text}]}


class BatchServerTests(unittest.TestCase):
    def test_scalar_worker_preserves_request_schema_for_feedback(self):
        replies = []
        coordinator = ScalarCoordinator(lambda value: value["schema_messages"][0]["content"],
                                        "model")
        coordinator.submit(request("A"), replies.append)
        coordinator.submit(request("B"), replies.append)
        self.assertEqual(replies, [{"model_id": "model", "text": "A"},
                                  {"model_id": "model", "text": "B"}])

    def test_interleaved_sequences_keep_independent_grammar_and_output(self):
        generator = Generator()
        replies = {}
        coordinator = BatchCoordinator(generator, Tokenizer(), lambda _: [object()], "model", 2048)
        coordinator.submit(request("A"), lambda value: replies.update(first=value))
        coordinator.submit(request("B"), lambda value: replies.update(second=value))
        generator.responses = [
            [SimpleNamespace(uid=2, token=66, finish_reason=None),
             SimpleNamespace(uid=1, token=65, finish_reason="stop")],
            [SimpleNamespace(uid=2, token=67, finish_reason="stop")],
        ]
        coordinator.step()
        coordinator.step()
        processors = [item[1]["logits_processors"][0][0] for item in generator.inserted]
        self.assertEqual((replies, len(coordinator.active), processors[0] is processors[1]),
                         ({"first": {"model_id": "model", "text": "A"},
                           "second": {"model_id": "model", "text": "BC"}}, 0, False))

    def test_identity_mismatch_is_rejected_before_generation(self):
        coordinator = BatchCoordinator(Generator(), Tokenizer(), lambda _: [object()], "model", 2048)
        with self.assertRaisesRegex(ValueError, "identity"):
            coordinator.submit(request("A", "another-model"), lambda _: None)

    def test_cancelled_client_releases_its_sequence(self):
        generator = Generator()
        coordinator = BatchCoordinator(generator, Tokenizer(), lambda _: [object()], "model", 2048)
        identifier = coordinator.submit(request("A"), lambda _: None)
        coordinator.cancel(identifier)
        self.assertEqual((generator.removed, coordinator.active), ([identifier], {}))
