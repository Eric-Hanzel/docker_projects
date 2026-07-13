import json
import tempfile
import unittest
from pathlib import Path

from app_server.client.handlers import SafeDefaultServerRequestHandler
from app_server.client.schemas import read_method_index, validate_method


class SafeDefaultServerRequestHandlerTests(unittest.TestCase):
    def test_command_approval_defaults_to_cancel(self) -> None:
        handler = SafeDefaultServerRequestHandler()
        action = handler.handle(
            "item/commandExecution/requestApproval",
            {"availableDecisions": ["accept", "cancel"]},
            {"name": "test-client"},
        )
        self.assertTrue(action.handled)
        self.assertEqual(action.result, {"decision": "cancel"})

    def test_dynamic_tool_call_returns_structured_failure(self) -> None:
        handler = SafeDefaultServerRequestHandler()
        action = handler.handle("item/tool/call", {}, {"name": "test-client"})
        self.assertTrue(action.handled)
        self.assertEqual(action.result["success"], False)
        self.assertEqual(action.result["contentItems"][0]["type"], "inputText")

    def test_unknown_request_is_unhandled(self) -> None:
        handler = SafeDefaultServerRequestHandler()
        action = handler.handle("unknown/method", {}, {"name": "test-client"})
        self.assertFalse(action.handled)


class SchemaMethodIndexTests(unittest.TestCase):
    def test_read_method_index_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ClientRequest.json").write_text(
                json.dumps({"oneOf": [{"properties": {"method": {"enum": ["thread/start"]}}}]}),
                encoding="utf-8",
            )
            (root / "ServerRequest.json").write_text(
                json.dumps({"oneOf": [{"properties": {"method": {"enum": ["item/tool/call"]}}}]}),
                encoding="utf-8",
            )
            methods = read_method_index(root)
            self.assertEqual(methods["client_requests"], ["thread/start"])
            self.assertEqual(methods["server_requests"], ["item/tool/call"])
            self.assertTrue(validate_method(methods, direction="client", method="thread/start")["ok"])
            self.assertFalse(validate_method(methods, direction="server", method="thread/start")["ok"])


if __name__ == "__main__":
    unittest.main()
