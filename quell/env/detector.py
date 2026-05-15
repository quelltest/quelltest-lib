"""
Detect where quelltest is running and select the appropriate container strategy.

Detection order matters:
  K8s first — pods can have a Docker socket that belongs to the node, not the pod.
  Named CI env vars next — most reliable per-environment signal.
  Filesystem checks last — only for local Docker and devcontainer cases.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class RuntimeEnvironment(Enum):
    """All environments where quelltest may be run."""

    LOCAL_DOCKER = "local_docker"
    DOCKER_IN_DOCKER = "dind"
    KUBERNETES_POD = "k8s"
    GITHUB_ACTIONS = "github_actions"
    GITLAB_CI = "gitlab_ci"
    CIRCLECI = "circleci"
    DEVCONTAINER = "devcontainer"
    NO_DOCKER = "no_docker"


@dataclass(frozen=True)
class EnvironmentStrategy:
    """How to start containers in a given runtime environment."""

    mode: str               # "testcontainers" | "dind" | "warn_skip" | "skip"
    docker_host: str | None
    network_mode: str
    ci_setup_hint: str | None  # printed when CI setup steps are needed


ENVIRONMENT_STRATEGY: dict[RuntimeEnvironment, EnvironmentStrategy] = {
    RuntimeEnvironment.LOCAL_DOCKER: EnvironmentStrategy(
        mode="testcontainers",
        docker_host=None,
        network_mode="bridge",
        ci_setup_hint=None,
    ),
    RuntimeEnvironment.GITHUB_ACTIONS: EnvironmentStrategy(
        mode="testcontainers",
        docker_host=None,
        network_mode="bridge",
        # Docker is available on all GH-hosted runners out of the box.
        ci_setup_hint=None,
    ),
    RuntimeEnvironment.GITLAB_CI: EnvironmentStrategy(
        mode="dind",
        docker_host="tcp://docker:2375",
        network_mode="host",
        ci_setup_hint=(
            "Add to .gitlab-ci.yml:\n"
            "  services:\n    - docker:dind\n"
            "  variables:\n    DOCKER_HOST: tcp://docker:2375"
        ),
    ),
    RuntimeEnvironment.DOCKER_IN_DOCKER: EnvironmentStrategy(
        mode="dind",
        docker_host="tcp://docker:2375",
        network_mode="host",
        ci_setup_hint=None,
    ),
    RuntimeEnvironment.KUBERNETES_POD: EnvironmentStrategy(
        mode="warn_skip",
        docker_host=None,
        network_mode="",
        ci_setup_hint=(
            "quelltest cannot start containers from inside a Kubernetes pod.\n"
            "Options:\n"
            "  1. Run `quell check` locally before pushing\n"
            "  2. Add a CI job with Docker access (GitHub Actions, GitLab DinD)\n"
            "  3. Use --with-containers=false to run pure-function tests only"
        ),
    ),
    RuntimeEnvironment.CIRCLECI: EnvironmentStrategy(
        mode="testcontainers",
        docker_host=None,
        network_mode="bridge",
        ci_setup_hint=(
            "Ensure 'setup_remote_docker' is in your CircleCI job config."
        ),
    ),
    RuntimeEnvironment.DEVCONTAINER: EnvironmentStrategy(
        mode="testcontainers",
        docker_host=None,
        network_mode="bridge",
        ci_setup_hint=None,
    ),
    RuntimeEnvironment.NO_DOCKER: EnvironmentStrategy(
        mode="skip",
        docker_host=None,
        network_mode="",
        ci_setup_hint=(
            "Install Docker Desktop: https://docs.docker.com/get-docker/"
        ),
    ),
}


def detect_environment() -> RuntimeEnvironment:
    """Return the RuntimeEnvironment for the current process.

    Pure function — reads env vars and filesystem only; never starts processes
    except for a cheap `docker info` probe as the last local-Docker check.
    """
    # K8s first: pods may have a Docker socket belonging to the node
    if Path("/var/run/secrets/kubernetes.io").exists():
        return RuntimeEnvironment.KUBERNETES_POD

    # Named CI environments — most reliable signal
    if os.getenv("GITHUB_ACTIONS") == "true":
        return RuntimeEnvironment.GITHUB_ACTIONS
    if os.getenv("GITLAB_CI") == "true":
        return RuntimeEnvironment.GITLAB_CI
    if os.getenv("CIRCLECI") == "true":
        return RuntimeEnvironment.CIRCLECI

    # Devcontainer / Codespaces
    if os.getenv("REMOTE_CONTAINERS") or os.getenv("CODESPACES"):
        return RuntimeEnvironment.DEVCONTAINER

    # DinD: inside a container AND Docker socket is mounted
    if Path("/.dockerenv").exists() and Path("/var/run/docker.sock").exists():
        return RuntimeEnvironment.DOCKER_IN_DOCKER

    # Local Docker Desktop — verify the socket actually responds
    if Path("/var/run/docker.sock").exists():
        try:
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return RuntimeEnvironment.LOCAL_DOCKER
        except Exception:
            pass

    return RuntimeEnvironment.NO_DOCKER


def get_strategy(env: RuntimeEnvironment | None = None) -> EnvironmentStrategy:
    """Return the container strategy for the given (or auto-detected) environment."""
    if env is None:
        env = detect_environment()
    return ENVIRONMENT_STRATEGY[env]


def can_start_containers(env: RuntimeEnvironment | None = None) -> bool:
    """Return True if the current environment supports starting containers."""
    strategy = get_strategy(env)
    return strategy.mode not in ("warn_skip", "skip")
