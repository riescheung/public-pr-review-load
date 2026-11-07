from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from qwen_overnight import build_agent


class OvernightTests(unittest.TestCase):
    def test_launch_agent_runs_the_controller_without_a_chat_or_terminal(self):
        agent = build_agent(Path("/tmp/review-manifest.json"), "overnight", 20, True)
        self.assertEqual(
            (agent["ProgramArguments"][-1], agent["RunAtLoad"], agent["KeepAlive"],
             agent["EnvironmentVariables"]["PYTHONUNBUFFERED"],
             "GH_TOKEN" in agent["EnvironmentVariables"]),
            ("--deploy", True, {"Crashed": True}, "1", False),
        )
