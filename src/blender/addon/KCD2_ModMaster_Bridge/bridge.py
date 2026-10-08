"""IPC communication client for KCD2 ModMaster Blender Bridge.

STRICTLY LOCALHOST (127.0.0.1). NEVER EXPOSES TO NETWORK.
"""
from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
from typing import Any, Callable

log = logging.getLogger("KCD2_ModMaster_Bridge.bridge")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 24952
BRIDGE_VERSION = "1.1.0"

# Main-thread command queue for Blender operators
_incoming_command_queue: queue.Queue[dict[str, Any]] = queue.Queue()
_listener_thread: threading.Thread | None = None
_stop_event = threading.Event()
_is_connected = False
_last_ping_time = 0.0


def is_connected() -> bool:
    """Returns whether the bridge is currently connected to ModMaster."""
    global _is_connected
    return _is_connected


def send_message_to_modmaster(
    payload: dict[str, Any],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    """Sends a one-off or command message to ModMaster IPC server on 127.0.0.1."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        data = (json.dumps(payload) + "\n").encode("utf-8")
        s.sendall(data)

        # Receive response
        buffer = b""
        while b"\n" not in buffer:
            chunk = s.recv(4096)
            if not chunk:
                break
            buffer += chunk

        s.close()
        if buffer:
            return json.loads(buffer.decode("utf-8").strip())
        return None
    except Exception as e:
        log.debug("IPC send failed to %s:%s: %s", host, port, e)
        return None


def ping_modmaster() -> bool:
    """Tests connection to ModMaster and updates connection status."""
    global _is_connected, _last_ping_time
    resp = send_message_to_modmaster({
        "command": "ping",
        "bridge_version": BRIDGE_VERSION,
        "timestamp": time.time(),
    })
    _is_connected = bool(resp and resp.get("status") in ("ok", "pong"))
    if _is_connected:
        _last_ping_time = time.time()
    return _is_connected


class BridgeClientListener(threading.Thread):
    """Background listener that maintains persistent connection or polls ModMaster."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        super().__init__(daemon=True, name="KCD2BridgeClientListener")
        self.host = host
        self.port = port

    def run(self) -> None:
        global _is_connected
        log.info("KCD2 ModMaster Bridge client listener started.")

        while not _stop_event.is_set():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3.0)
                s.connect((self.host, self.port))
                _is_connected = True

                # Send initial handshake
                handshake = {
                    "command": "handshake",
                    "bridge_version": BRIDGE_VERSION,
                    "client": "Blender",
                }
                s.sendall((json.dumps(handshake) + "\n").encode("utf-8"))

                buffer = ""
                s.settimeout(1.0)
                while not _stop_event.is_set():
                    try:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk.decode("utf-8", errors="replace")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if line:
                                try:
                                    cmd_data = json.loads(line)
                                    _incoming_command_queue.put(cmd_data)
                                except Exception as err:
                                    log.warning("Bad JSON from ModMaster: %s", err)
                    except socket.timeout:
                        continue
                    except Exception as loop_err:
                        log.debug("Socket loop error: %s", loop_err)
                        break

                s.close()
            except Exception:
                _is_connected = False
                # Wait before retry
                for _ in range(20):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.1)

        _is_connected = False
        log.info("KCD2 ModMaster Bridge client listener stopped.")


def start_bridge_listener() -> None:
    """Starts the background bridge listener thread."""
    global _listener_thread, _stop_event
    if _listener_thread and _listener_thread.is_alive():
        return
    _stop_event.clear()
    _listener_thread = BridgeClientListener()
    _listener_thread.start()


def stop_bridge_listener() -> None:
    """Stops the background bridge listener thread."""
    global _listener_thread, _stop_event
    _stop_event.set()
    _listener_thread = None


def get_next_command() -> dict[str, Any] | None:
    """Retrieves next command to process on Blender's main thread."""
    try:
        return _incoming_command_queue.get_nowait()
    except queue.Empty:
        return None
