"""Tests for WebSocket push – ConnectionManager and /ws endpoint."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

import dashboard.server as dashboard_module
from dashboard.server import app, ConnectionManager, manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine in a fresh event loop (for unit-testing async methods)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# ConnectionManager – unit tests (no HTTP layer)
# ---------------------------------------------------------------------------

def test_connect_adds_to_active():
    mgr = ConnectionManager()
    ws = AsyncMock()
    _run(mgr.connect(ws))
    assert ws in mgr.active


def test_connect_accepts_websocket():
    mgr = ConnectionManager()
    ws = AsyncMock()
    _run(mgr.connect(ws))
    ws.accept.assert_called_once()


def test_disconnect_removes_from_active():
    mgr = ConnectionManager()
    ws = AsyncMock()
    mgr.active.append(ws)
    mgr.disconnect(ws)
    assert ws not in mgr.active


def test_disconnect_is_idempotent():
    """Disconnecting a socket that isn't in active must not raise."""
    mgr = ConnectionManager()
    ws = AsyncMock()
    mgr.disconnect(ws)  # should not raise


def test_broadcast_sends_to_all_connections():
    mgr = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    mgr.active = [ws1, ws2]
    msg = {"type": "ping", "timestamp": "2026-04-12T00:00:00", "data": None}
    _run(mgr.broadcast(msg))
    ws1.send_json.assert_called_once_with(msg)
    ws2.send_json.assert_called_once_with(msg)


def test_broadcast_removes_dead_connections():
    """If send_json raises, the dead socket is removed from active."""
    mgr = ConnectionManager()
    live = AsyncMock()
    dead = AsyncMock()
    dead.send_json.side_effect = RuntimeError("disconnected")
    mgr.active = [live, dead]
    _run(mgr.broadcast({"type": "ping"}))
    assert dead not in mgr.active
    assert live in mgr.active


def test_broadcast_no_connections_does_not_raise():
    mgr = ConnectionManager()
    _run(mgr.broadcast({"type": "ping"}))  # should not raise


def test_broadcast_message_content_is_exact():
    mgr = ConnectionManager()
    ws = AsyncMock()
    mgr.active = [ws]
    msg = {"type": "live_updated", "timestamp": "T", "data": None}
    _run(mgr.broadcast(msg))
    ws.send_json.assert_called_once_with(msg)


# ---------------------------------------------------------------------------
# /ws endpoint – integration tests via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def ws_client():
    """TestClient that triggers startup events (required for WS support)."""
    with TestClient(app) as client:
        yield client


def test_ws_endpoint_accepts_connection(ws_client):
    with ws_client.websocket_connect("/ws") as ws:
        # Connection accepted – no exception raised
        pass


def test_ws_endpoint_connection_appears_in_manager(ws_client):
    before = len(manager.active)
    with ws_client.websocket_connect("/ws"):
        assert len(manager.active) == before + 1
    # After disconnect the socket is removed
    assert len(manager.active) == before


def test_ws_endpoint_multiple_connections(ws_client):
    before = len(manager.active)
    with ws_client.websocket_connect("/ws"):
        with ws_client.websocket_connect("/ws"):
            assert len(manager.active) == before + 2
        assert len(manager.active) == before + 1
    assert len(manager.active) == before


def test_ws_broadcast_reaches_connected_client(ws_client):
    """Broadcast from server side should be receivable by a connected client."""
    with ws_client.websocket_connect("/ws") as ws:
        msg = {"type": "ping", "timestamp": "2026-04-12T00:00:00", "data": None}
        asyncio.run(manager.broadcast(msg))
        received = ws.receive_json()
        assert received["type"] == "ping"
