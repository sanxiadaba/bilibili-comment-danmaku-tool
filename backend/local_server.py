"""从首选端口开始找一个空闲端口，起 ThreadingHTTPServer。"""

import errno
from http.server import ThreadingHTTPServer


DEFAULT_PORT = 8001
MAX_PORT_ATTEMPTS = 100
IPV6_LOOPBACK_HOSTS = {"::1", "[::1]"}


def ensure_ipv4_bind_host(host):
    """Reject IPv6 loopback instead of letting an AF_INET bind fail with an opaque error.

    ``ThreadingHTTPServer`` binds an AF_INET socket, so ``::1`` passes the loopback allow
    list but can never be bound. Say so clearly and point at the IPv4 loopback.
    """
    normalized = str(host or "").strip().lower()
    if normalized in IPV6_LOOPBACK_HOSTS:
        raise ValueError("暂不支持 IPv6 回环地址 ::1，请改用 127.0.0.1 或 localhost")
    return normalized


def create_threading_server(host, preferred_port, handler, max_attempts=MAX_PORT_ATTEMPTS):
    ensure_ipv4_bind_host(host)
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
