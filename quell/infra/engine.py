"""
Container engine — lifecycle management for ephemeral test infrastructure.

Containers are:
  - Started once per quell check run (shared across all functions needing them)
  - Reused across consecutive runs via the keep-alive lockfile
  - Destroyed on quell teardown or clean process exit
  - Never started when the runtime environment does not support Docker

Phase 2 isolation:
  Each verification subprocess receives QUELL_TRANSACTION_ROLLBACK=true so
  generated fixtures wrap DB operations in a transaction that rolls back after
  the test — ensuring Phase 1 and Phase 2 always start from the same state.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from quell.infra.lockfile import (
    container_alive,
    read_lock,
    stop_container,
    teardown_all,
    write_lock,
)
from quell.infra.specs import (
    CONTAINER_SPECS,
    EPHEMERAL_CREDS,
    ContainerSpec,
    show_trust_message_once,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60   # seconds to wait for container ready


@dataclass
class ContainerSession:
    """Holds the connection URLs for all running ephemeral containers."""

    _urls: dict[str, str] = field(default_factory=dict)

    def register(self, tag: str, url: str) -> None:
        self._urls[tag] = url

    def get_url(self, tag: str) -> str | None:
        return self._urls.get(tag)

    @property
    def env_vars(self) -> dict[str, str]:
        """
        Build the env dict to inject into verification subprocesses.
        Includes connection URLs and QUELL_TRANSACTION_ROLLBACK=true.
        """
        env = dict(os.environ)
        for tag, url in self._urls.items():
            spec = CONTAINER_SPECS.get(tag)
            if spec:
                env[spec.connection_env_key] = url
        env["QUELL_TRANSACTION_ROLLBACK"] = "true"
        return env

    @property
    def tags(self) -> set[str]:
        return set(self._urls)


class ContainerEngine:
    """
    Manages ephemeral container lifecycle for a quell check run.

    Usage::

        engine = ContainerEngine()
        session = engine.prepare({"postgres", "redis"})
        # run verification with session.env_vars
        engine.teardown()
    """

    def __init__(
        self,
        lock_path: Path = Path(".quellgraph") / "containers.lock",
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._lock_path = lock_path
        self._timeout = timeout
        self._started_this_run: list[str] = []

    def prepare(self, tags: set[str]) -> ContainerSession:
        """
        Ensure all required containers are running. Returns a ContainerSession.

        Shows the trust message on first run per project.
        Reuses running containers from the lockfile before starting new ones.
        """
        if not tags:
            return ContainerSession()

        show_trust_message_once()

        session = ContainerSession()
        for tag in sorted(tags):
            spec = CONTAINER_SPECS.get(tag)
            if spec is None:
                logger.warning("No container spec for tag '%s' — skipping", tag)
                continue
            url = self._start_or_reuse(spec)
            if url:
                session.register(tag, url)

        return session

    def teardown(self, tags: set[str] | None = None) -> list[str]:
        """
        Stop containers. If tags is None, tears down all containers in the lockfile.
        """
        if tags is None:
            return teardown_all(self._lock_path)

        torn: list[str] = []
        lock = read_lock(self._lock_path)
        for tag in tags:
            entry = lock.get(tag)
            if entry and stop_container(entry["container_id"]):
                torn.append(tag)
        return torn

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _start_or_reuse(self, spec: ContainerSpec) -> str | None:
        """Check lockfile for a running container first; start new if needed."""
        lock = read_lock(self._lock_path)
        entry = lock.get(spec.tag)
        if entry and container_alive(entry["container_id"]):
            logger.debug("Reusing %s container %s", spec.tag, entry["container_id"][:12])
            return entry["url"]
        return self._start(spec)

    def _start(self, spec: ContainerSpec) -> str | None:
        """Start a new container for the given spec. Returns connection URL or None."""
        creds = EPHEMERAL_CREDS.get(spec.tag, {})
        env_args: list[str] = []
        for k, v in creds.items():
            if v is not None:
                env_args += ["-e", f"{k.upper()}={v}"]

        # Extra spec env vars
        for k, v in spec.env_vars.items():
            env_args += ["-e", f"{k}={v}"]

        host_port = _find_free_port()
        cmd = [
            "docker", "run", "-d",
            "--rm",
            "-p", f"{host_port}:{spec.port}",
            *env_args,
            spec.image,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(
                    "Failed to start %s container: %s", spec.tag, result.stderr.strip()
                )
                return None
            container_id = result.stdout.strip()
        except Exception as exc:
            logger.error("docker run failed for %s: %s", spec.tag, exc)
            return None

        url = spec.connection_url_template.format(host="127.0.0.1", port=host_port)

        if not self._wait_ready(spec, container_id, url):
            stop_container(container_id)
            return None

        write_lock(spec.tag, container_id, url, spec.image, self._lock_path)
        self._started_this_run.append(spec.tag)
        logger.info("Started %s container %s → %s", spec.tag, container_id[:12], url)
        return url

    def _wait_ready(self, spec: ContainerSpec, container_id: str, url: str) -> bool:
        """Block until the container is ready to accept connections."""
        deadline = time.time() + self._timeout

        if spec.wait_strategy == "log":
            return self._wait_log(container_id, spec.wait_value, deadline)
        if spec.wait_strategy == "http":
            return self._wait_http(url, spec.wait_value, deadline)
        if spec.wait_strategy == "port":
            return self._wait_port("127.0.0.1", spec.port, deadline)
        return True

    def _wait_log(self, container_id: str, sentinel: str, deadline: float) -> bool:
        while time.time() < deadline:
            try:
                out = subprocess.run(
                    ["docker", "logs", container_id],
                    capture_output=True, text=True, timeout=5,
                ).stdout + subprocess.run(
                    ["docker", "logs", container_id],
                    capture_output=True, text=True, timeout=5,
                ).stderr
                if sentinel in out:
                    return True
            except Exception:
                pass
            time.sleep(1)
        logger.error("Container did not emit '%s' within timeout", sentinel)
        return False

    def _wait_http(self, base_url: str, path: str, deadline: float) -> bool:
        import urllib.request
        probe = base_url.rstrip("/") + path
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(probe, timeout=3):
                    return True
            except Exception:
                time.sleep(2)
        logger.error("Container HTTP probe %s did not respond within timeout", probe)
        return False

    def _wait_port(self, host: str, port: int, deadline: float) -> bool:
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=2):
                    return True
            except OSError:
                time.sleep(1)
        logger.error("Container port %s:%s not open within timeout", host, port)
        return False


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]
