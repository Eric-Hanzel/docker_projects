import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_SERVER = ROOT / "app_server"


def load_runner():
    sys.path.insert(0, str(APP_SERVER))
    try:
        spec = importlib.util.spec_from_file_location("apdv1_runner_under_test", APP_SERVER / "runner.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(APP_SERVER))
        except ValueError:
            pass


class FakeClient:
    def __init__(self, messages):
        self.thread_id = "parent-thread"
        self.turn_id = "parent-turn"
        self.messages = list(messages)
        self.handled = []
        self.proc = None

    def recv(self, timeout, allow_idle=False):
        if not self.messages:
            return None
        return self.messages.pop(0)

    def handle_message(self, msg):
        self.handled.append(msg)


class RunnerTurnWaitTests(unittest.TestCase):
    def test_result_defaults_to_success_for_successful_terminal_status(self) -> None:
        runner = load_runner()

        self.assertEqual(runner.result_from_state({"status": "COMPLETED_SUCCESS"}), "success")
        self.assertEqual(runner.result_from_state({"status": "COMPLETED_CONDITIONAL_SUCCESS"}), "success")
        self.assertEqual(runner.result_from_state({"status": "COMPLETED_FAILED"}), "failed")

    def test_result_preserves_explicit_state_result(self) -> None:
        runner = load_runner()

        self.assertEqual(
            runner.result_from_state({"status": "COMPLETED_SUCCESS", "result": "custom"}),
            "custom",
        )

    def test_wait_ignores_subagent_turn_completion(self) -> None:
        runner = load_runner()
        client = FakeClient(
            [
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "child-thread",
                        "turn": {"id": "child-turn", "status": "completed"},
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "parent-thread",
                        "turn": {"id": "parent-turn", "status": "completed"},
                    },
                },
            ]
        )

        outcome, code = runner.wait_for_turn_completion(client, 5)

        self.assertEqual(outcome, "completed")
        self.assertEqual(code, 0)
        self.assertEqual(len(client.handled), 2)


if __name__ == "__main__":
    unittest.main()
