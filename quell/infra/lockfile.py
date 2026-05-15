"""
Container keep-alive lockfile — reuse running containers across consecutive runs.

Location: .quellgraph/containers.lock  (JSON)

Schema per entry:
  { "container_id": str, "url": str, "started_at": float, "image": str }
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCK_PATH = Path(".quellgraph") / "containers.lock"


def read_lock(lock_path: Path = _LOCK_PATH) -> dict[str, dict]:
    """Return the current lockfile contents (empty dict if missing or corrupt)."""
    if not lock_path.exists():
        return {}
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_lock(
    tag: str,
    container_id: str,
    url: str,
    image: str,
    lock_path: Path = _LOCK_PATH,
) -> None:
    """Upsert one container entry into the lockfile."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    data = read_lock(lock_path)
    data[tag] = {
        "container_id": container_id,
        "url": url,
        "started_at": time.time(),
        "image": image,
    }
    tmp = lock_path.with_suffix(".lock.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(lock_path)


def remove_lock_entry(tag: str, lock_path: Path = _LOCK_PATH) -> None:
    """Remove one tag from the lockfile."""
    data = read_lock(lock_path)
    data.pop(tag, None)
    if data:
        tmp = lock_path.with_suffix(".lock.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(lock_path)
    else:
        lock_path.unlink(missing_ok=True)


def clear_lock(lock_path: Path = _LOCK_PATH) -> None:
    """Delete the entire lockfile."""
    lock_path.unlink(missing_ok=True)


def container_alive(container_id: str) -> bool:
    """Return True if the given Docker container ID is currently running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        return False


def stop_container(container_id: str) -> bool:
    """Stop and remove a container. Returns True on success."""
    try:
        subprocess.run(["docker", "stop", container_id], capture_output=True, timeout=30)
        subprocess.run(["docker", "rm", container_id], capture_output=True, timeout=10)
        return True
    except Exception as exc:
        logger.warning("Could not stop container %s: %s", container_id, exc)
        return False


def teardown_all(lock_path: Path = _LOCK_PATH) -> list[str]:
    """Stop all containers listed in the lockfile. Returns list of tags torn down."""
    data = read_lock(lock_path)
    torn_down: list[str] = []
    for tag, entry in data.items():
        cid = entry.get("container_id", "")
        if cid and stop_container(cid):
            torn_down.append(tag)
            logger.info("Stopped %s container %s", tag, cid[:12])
    clear_lock(lock_path)
    return torn_down
