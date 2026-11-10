"""Single source of truth for the writable runtime data directory.

Frozen (Nuitka/PyInstaller) builds unpack the package into ``_internal``, so deriving state file
paths from ``__file__`` silently writes caches inside the installation directory. The server and
the desktop entry publish the real data directory through ``BILIBILI_TOOL_DATA_DIR``.
"""

import os
from pathlib import Path

DATA_DIR_ENV = "BILIBILI_TOOL_DATA_DIR"
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


def default_data_dir():
    configured = os.environ.get(DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    return _PACKAGE_ROOT / "data"


def publish_data_dir(path):
    """Point this process at its writable data directory (used by the server entry points)."""
    if not path:
        return None
    resolved = Path(path).resolve()
    os.environ[DATA_DIR_ENV] = str(resolved)
    return resolved


def state_file(name):
    return default_data_dir() / name
