from __future__ import annotations

import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def load_fixture(directory: Path, name: str) -> Any:
    return json.loads((directory / name).read_text(encoding="utf-8"))


class RpcFixtureServer:
    def __init__(
        self,
        fixture_dir: Path,
        rpc_user: str = "test-user",
        rpc_password: str = "test-password",
    ) -> None:
        self.fixture_dir = fixture_dir
        self.rpc_user = rpc_user
        self.rpc_password = rpc_password
        self.request_counts: Counter[str] = Counter()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._server.owner = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()

    def _handler_class(self):
        fixture_dir = self.fixture_dir

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                owner = self.server.owner  # type: ignore[attr-defined]
                expected = f"Basic {self._basic_token(owner.rpc_user, owner.rpc_password)}"
                if self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error":"unauthorized"}')
                    return

                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(
                    self.rfile.read(content_length).decode("utf-8")
                )
                method = payload["method"]
                params = payload.get("params", [])
                owner.request_counts[method] += 1

                result = self._resolve_fixture(fixture_dir, method, params)
                body = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": result,
                        "error": None,
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                return

            def _resolve_fixture(
                self, fixture_root: Path, method: str, params: list[Any]
            ) -> Any:
                if method == "getblockhash":
                    return load_fixture(
                        fixture_root, f"getblockhash-{params[0]}.json"
                    )
                if method == "getblockheader":
                    return load_fixture(
                        fixture_root, f"getblockheader-{params[0]}.json"
                    )
                return load_fixture(fixture_root, f"{method}.json")

            @staticmethod
            def _basic_token(username: str, password: str) -> str:
                import base64

                token = f"{username}:{password}".encode("utf-8")
                return base64.b64encode(token).decode("ascii")

        return Handler
