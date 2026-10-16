"""Storage Path Resolution — Canonical project root and data directory resolution.

Guarantees consistent discovery of:
- `data/` directory
- `data/cache/` directory
- Seed fixtures
regardless of the process working directory (CWD).
"""

from pathlib import Path
import os
from typing import Optional, Union


def get_project_root() -> Path:
    """Resolve the authoritative YOGI project root directory.

    Searches upward from this module's file location until a directory containing
    `pyproject.toml` or `AGENTS.md` is found, with fallback to 3 levels up.
    Can be overridden via the `YOGI_PROJECT_ROOT` environment variable.
    """
    env_root = os.getenv("YOGI_PROJECT_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.exists():
            return p

    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() or (candidate / "AGENTS.md").is_file():
            return candidate

    return Path(__file__).resolve().parents[3]


def get_data_dir(custom_path: Optional[Union[Path, str]] = None) -> Path:
    """Resolve the authoritative data directory.

    If custom_path is provided:
      - If absolute, returns resolved custom_path.
      - If relative, anchors it to get_project_root().
    Can be overridden via the `YOGI_DATA_DIR` environment variable.
    Defaults to `{project_root}/data`.
    """
    if custom_path is not None:
        p = Path(custom_path)
        if not p.is_absolute():
            return (get_project_root() / p).resolve()
        return p.resolve()

    env_data = os.getenv("YOGI_DATA_DIR")
    if env_data:
        return Path(env_data).resolve()

    return (get_project_root() / "data").resolve()


def get_cache_dir(custom_path: Optional[Union[Path, str]] = None) -> Path:
    """Resolve the authoritative cache directory (`{data_dir}/cache`).

    Can be overridden via the `YOGI_CACHE_DIR` environment variable.
    """
    if custom_path is not None:
        p = Path(custom_path)
        if not p.is_absolute():
            return (get_project_root() / p).resolve()
        return p.resolve()

    env_cache = os.getenv("YOGI_CACHE_DIR")
    if env_cache:
        return Path(env_cache).resolve()

    return (get_data_dir() / "cache").resolve()
