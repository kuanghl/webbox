"""Small shared helpers for the frontends."""

from __future__ import annotations

import socket


def check_port_available(host: str, port: int) -> bool:
    """Return whether a TCP port can be bound right now.

    Used by the web frontends (NiceGUI/Flet) to fail fast with a clear
    hint instead of uvicorn's raw ``address already in use`` error.

    Args:
        host: Bind address to test.
        port: Port to test.

    Returns:
        True when the bind succeeds, False when the port is taken.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True
