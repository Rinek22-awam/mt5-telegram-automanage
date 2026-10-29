"""One copy at a time: each program holds a local port while it runs.

Two bots would read the same Telegram updates and could execute a setup twice; two
readers would fight over the Telegram login file. The port is freed by Windows the
moment the program exits, even after a crash, so there is no stale lock to clean up.
"""
import socket

BOT_PORT = 47651
READER_PORT = 47652


def claim(port: int):
    """Hold the port for this program's lifetime. None if another copy already has it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
    except OSError:
        s.close()
        return None
    return s


def is_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False
