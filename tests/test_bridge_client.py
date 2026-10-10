"""Bridge client: the per-session token travels with every request, read fresh from the token file."""
import json
import socket
import threading

import pytest

from almond_mcp import bridge_client, cli


class FakeBridge:
    """One-request-per-connection server speaking the bridge framing; answers like a protocol-2 bridge."""

    def __init__(self, token="t" * 64):
        self.token, self.seen = token, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                head = conn.recv(4)
                if len(head) < 4:                      # a bare connect (doctor's port check): nothing to answer
                    continue
                n = int.from_bytes(head, "big")
                data = b""
                while len(data) < n:
                    data += conn.recv(n - len(data))
                msg = json.loads(data)
                self.seen.append(msg)
                if msg.get("token") != self.token:
                    reply = {"status": "error", "code": "unauthorized", "message": "no token"}
                elif msg.get("type") == "ping":
                    reply = {"status": "ok", "bridge": "almondbridge", "version": "9.9.9", "protocol": 2,
                             "python_package": "almond-mcp@9.9.9"}
                else:
                    reply = {"status": "success", "echo": msg.get("type")}
                body = json.dumps(reply).encode()
                conn.sendall(len(body).to_bytes(4, "big") + body)

    def close(self):
        self.sock.close()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_client.paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.delenv(bridge_client.TOKEN_ENV, raising=False)
    return tmp_path


def test_token_from_file_then_env(home, monkeypatch):
    assert bridge_client.token() is None
    (home / "bridge.token").write_text("abc\n", encoding="utf-8")
    assert bridge_client.token() == "abc"
    monkeypatch.setenv(bridge_client.TOKEN_ENV, "xyz")
    assert bridge_client.token() == "xyz"


def test_with_token_adds_it_to_json_objects_only(home):
    (home / "bridge.token").write_text("abc", encoding="utf-8")
    assert json.loads(bridge_client.with_token(b'{"type": "ping"}')) == {"type": "ping", "token": "abc"}
    assert bridge_client.with_token(b"[1, 2]") == b"[1, 2]"
    assert bridge_client.with_token(b"not json") == b"not json"


def test_send_carries_the_current_token_and_rereads_it(home):
    bridge = FakeBridge(token="first")
    try:
        (home / "bridge.token").write_text("first", encoding="utf-8")
        assert json.loads(bridge_client.send(b'{"type": "execute"}', port=bridge.port)) == {"status": "success", "echo": "execute"}
        # Rhino restarted: a new token; the next request picks it up without a client restart
        bridge.token = "second"
        (home / "bridge.token").write_text("second", encoding="utf-8")
        assert json.loads(bridge_client.send(b'{"type": "execute"}', port=bridge.port))["status"] == "success"
        assert [m["token"] for m in bridge.seen] == ["first", "second"]
    finally:
        bridge.close()


def test_doctor_reports_token_problems_and_success(home, monkeypatch, capsys):
    bridge = FakeBridge(token="good")
    try:
        monkeypatch.setattr(cli, "BRIDGE_PORT", bridge.port)
        monkeypatch.setattr(bridge_client, "PORT", bridge.port)
        cli.cmd_doctor(None)
        assert "no token at" in capsys.readouterr().out
        (home / "bridge.token").write_text("stale", encoding="utf-8")
        cli.cmd_doctor(None)
        assert "is not this Rhino session's" in capsys.readouterr().out
        (home / "bridge.token").write_text("good", encoding="utf-8")
        cli.cmd_doctor(None)
        out = capsys.readouterr().out
        assert "almondbridge 9.9.9 (protocol 2)" in out and "pairs with almond-mcp@9.9.9" in out
    finally:
        bridge.close()
