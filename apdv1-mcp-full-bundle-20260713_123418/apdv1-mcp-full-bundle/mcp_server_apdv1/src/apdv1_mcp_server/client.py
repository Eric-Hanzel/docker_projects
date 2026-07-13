import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import Config


class Apdv1ApiError(RuntimeError):
    pass


class Apdv1ApiClient:
    def __init__(self, config: Config):
        self.config = config

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self.config.api_base}{path}"
        if params:
            clean = {key: value for key, value in params.items() if value is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        return url

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, text: bool = False) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._url(path), data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
                if text:
                    return raw
                data = json.loads(raw) if raw else {}
                if isinstance(data, dict) and data.get("ok") is False:
                    raise Apdv1ApiError(str(data.get("error", data)))
                return data
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise Apdv1ApiError(f"APDv1 API HTTP {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            raise Apdv1ApiError(f"APDv1 API unavailable at {self.config.api_base}: {exc.reason}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/healthz")

    def status(self, limit: int = 10) -> dict[str, Any]:
        return self._request("GET", f"/status?{urllib.parse.urlencode({'limit': limit})}")

    def deploy(self, url: str, extras: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"url": url, "extras": dict(extras or {}), "source": "mcp"}
        return self._request("POST", "/deploy", payload)

    def deploy_batch(self, targets: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", "/deploy", {"targets": targets, "source": "mcp"})

    def request_record(self, request_id: str) -> dict[str, Any]:
        return self._request("GET", f"/requests/{urllib.parse.quote(request_id)}")

    def tail(self, request_id: str | None = None, file: str = "trace", lines: int = 80) -> str:
        if request_id:
            quoted = urllib.parse.quote(request_id)
            query = urllib.parse.urlencode({"file": file, "lines": lines})
            return self._request("GET", f"/requests/{quoted}/tail?{query}", text=True)
        return self._request("GET", f"/logs?{urllib.parse.urlencode({'lines': lines})}", text=True)

    def cancel(self, request_id: str) -> dict[str, Any]:
        quoted = urllib.parse.quote(request_id)
        return self._request("POST", f"/requests/{quoted}/cancel", {"source": "mcp"})

    def abort_current(self) -> dict[str, Any]:
        return self._request("POST", "/abort-current", {"source": "mcp"})

    def stop_service(self) -> dict[str, Any]:
        return self._request("POST", "/stop", {"source": "mcp"})
