import os
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ServerRequestAction:
    handled: bool
    result: Any | None = None
    error: dict[str, Any] | None = None
    note: str = ""


class ServerRequestHandler(Protocol):
    def handle(self, method: str, params: dict[str, Any], client_info: dict[str, Any]) -> ServerRequestAction:
        ...


class SafeDefaultServerRequestHandler:
    """Non-interactive handler with safe defaults for unattended agents."""

    def __init__(self, *, approval_decision: str | None = None):
        self.approval_decision = approval_decision

    def _approval_decision(self, available: Any) -> str:
        configured = self.approval_decision or os.environ.get("APP_SERVER_APPROVAL_DECISION", "cancel").strip() or "cancel"
        if isinstance(available, list) and available:
            choices = {str(item) for item in available}
            if configured in choices:
                return configured
            if "cancel" in choices:
                return "cancel"
            if "decline" in choices:
                return "decline"
            return str(available[0])
        return configured

    def handle(self, method: str, params: dict[str, Any], client_info: dict[str, Any]) -> ServerRequestAction:
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            decision = self._approval_decision(params.get("availableDecisions"))
            return ServerRequestAction(True, {"decision": decision}, note=f"approval:{decision}")

        if method == "item/permissions/requestApproval":
            return ServerRequestAction(
                True,
                {"permissions": {"type": "none"}, "scope": "turn", "strictAutoReview": True},
                note="permissions:none",
            )

        if method == "mcpServer/elicitation/request":
            return ServerRequestAction(True, {"action": "cancel"}, note="mcp_elicitation:cancel")

        if method == "item/tool/requestUserInput":
            return ServerRequestAction(True, {"answers": {}}, note="user_input:empty")

        if method == "item/tool/call":
            return ServerRequestAction(
                True,
                {
                    "success": False,
                    "contentItems": [
                        {"type": "inputText", "text": f"Unsupported dynamic tool call in {client_info['name']}"}
                    ],
                },
                note="dynamic_tool:unsupported",
            )

        if method in {"applyPatchApproval", "execCommandApproval"}:
            return ServerRequestAction(True, {"decision": "denied"}, note=f"{method}:denied")

        if method == "account/chatgptAuthTokens/refresh":
            return ServerRequestAction(
                True,
                error={"code": -32601, "message": "ChatGPT token refresh is not available in this client"},
                note="auth_refresh:unsupported",
            )

        return ServerRequestAction(False)
