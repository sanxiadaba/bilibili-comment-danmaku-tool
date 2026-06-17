import errno
from http.server import ThreadingHTTPServer


DEFAULT_PORT = 8001
MAX_PORT_ATTEMPTS = 100


def create_threading_server(host, preferred_port, handler, max_attempts=MAX_PORT_ATTEMPTS):
    start_port = int(preferred_port or DEFAULT_PORT)
    for port in range(start_port, start_port + int(max_attempts)):
        try:
            return ThreadingHTTPServer((host, port), handler), port
        except OSError as exc:
            if not is_address_in_use(exc):
                raise
    raise OSError(f"No free port found from {start_port} to {start_port + int(max_attempts) - 1}")


def is_address_in_use(exc):
    return getattr(exc, "errno", None) in {errno.EADDRINUSE, errno.EACCES, 10048, 10013}
