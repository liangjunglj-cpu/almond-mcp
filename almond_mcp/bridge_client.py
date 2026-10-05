"""Client side of the Rhino bridge protocol (almondbridge on 127.0.0.1:5000).

Framing: 4-byte big-endian length + UTF-8 JSON, one request per connection. The bridge executes C#
for its clients, so every request carries this Rhino session's token: almondbridge writes a fresh one
to ``%LOCALAPPDATA%\\Almond\\bridge.token`` each time Rhino starts (ALMOND_BRIDGE_TOKEN overrides it,
e.g. for a bridge on another account). The token is read per request, so restarting Rhino needs no
restart here. Bridges before protocol 2 ignore the field.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from . import paths

HOST = "127.0.0.1"
PORT = 5000
TOKEN_ENV = "ALMOND_BRIDGE_TOKEN"


def token_path() -> Path:
    return paths.user_data_dir() / "bridge.token"


def token() -> str | None:
    """This Rhino session's bridge token, or None when no bridge has written one."""
    value = os.environ.get(TOKEN_ENV, "").strip()
    if value:
        return value
    try:
        return token_path().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def with_token(payload: bytes) -> bytes:
    """The JSON request with the session token added (unchanged when there is none or it is not an object)."""
    value = token()
    if not value:
        return payload
    try:
        message = json.loads(payload)
    except ValueError:
        return payload
    if not isinstance(message, dict):
        return payload
    message["token"] = value
    return json.dumps(message).encode("utf-8")


def _recv_exact(s: socket.socket, n: int, what: str) -> bytes:
    data = b""
    while len(data) < n:
        chunk = s.recv(min(65536, n - len(data)))
        if not chunk:
            raise ConnectionError(f"Bridge closed connection while reading response {what}.")
        data += chunk
    return data


def send(payload: bytes, timeout: float = 60.0, host: str | None = None, port: int | None = None) -> str:
    """Send one JSON request (bytes) with the session token and return the bridge's JSON reply text."""
    payload = with_token(payload)
    with socket.create_connection((host or HOST, port or PORT), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(len(payload).to_bytes(4, "big") + payload)
        length = int.from_bytes(_recv_exact(s, 4, "header"), "big")
        return _recv_exact(s, length, "body").decode("utf-8")


def ping(timeout: float = 5.0) -> dict:
    """The bridge's ping reply ({"status": "ok", "version": ..., "protocol": 2, ...}) or an error dict."""
    try:
        reply = json.loads(send(json.dumps({"type": "ping"}).encode("utf-8"), timeout=timeout))
    except OSError as exc:
        return {"status": "error", "code": "unreachable", "message": str(exc)}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    return reply if isinstance(reply, dict) else {"status": "error", "message": "Unexpected reply."}
