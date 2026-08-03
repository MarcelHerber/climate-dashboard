from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

USER_AGENT = (
    "climate-dashboard/1.0 "
    "(+https://github.com/MarcelHerber/climate-dashboard; DWD open data updater)"
)


def download(url: str, *, timeout: int = 60, attempts: int = 5) -> bytes:
    """Download a URL with retries and a descriptive user agent."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 12))
    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last_error}")


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically so a failed run cannot corrupt the live file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
