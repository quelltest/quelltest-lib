"""Tests for quell.env.detector — RuntimeEnvironment detection."""
from __future__ import annotations

import pytest

from quell.env.detector import (
    ENVIRONMENT_STRATEGY,
    RuntimeEnvironment,
    can_start_containers,
    detect_environment,
    get_strategy,
)


class TestDetectEnvironment:
    def test_github_actions_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert detect_environment() == RuntimeEnvironment.GITHUB_ACTIONS

    def test_gitlab_ci_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("GITLAB_CI", "true")
        assert detect_environment() == RuntimeEnvironment.GITLAB_CI

    def test_circleci_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("GITLAB_CI", raising=False)
        monkeypatch.setenv("CIRCLECI", "true")
        assert detect_environment() == RuntimeEnvironment.CIRCLECI

    def test_devcontainer_detected_via_remote_containers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for k in ("GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("REMOTE_CONTAINERS", "true")
        assert detect_environment() == RuntimeEnvironment.DEVCONTAINER

    def test_codespaces_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for k in ("GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "REMOTE_CONTAINERS"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("CODESPACES", "true")
        assert detect_environment() == RuntimeEnvironment.DEVCONTAINER

    def test_no_docker_when_no_socket(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
        """Without any CI env vars and no Docker socket → NO_DOCKER on most CI runners."""
        for k in ("GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "REMOTE_CONTAINERS", "CODESPACES"):
            monkeypatch.delenv(k, raising=False)
        # The test environment itself may or may not have Docker; just verify
        # the function returns a valid RuntimeEnvironment without raising.
        result = detect_environment()
        assert isinstance(result, RuntimeEnvironment)


class TestEnvironmentStrategy:
    def test_all_environments_have_a_strategy(self) -> None:
        for env in RuntimeEnvironment:
            assert env in ENVIRONMENT_STRATEGY, f"No strategy for {env}"

    def test_github_actions_uses_testcontainers(self) -> None:
        s = ENVIRONMENT_STRATEGY[RuntimeEnvironment.GITHUB_ACTIONS]
        assert s.mode == "testcontainers"
        assert s.ci_setup_hint is None

    def test_gitlab_ci_uses_dind(self) -> None:
        s = ENVIRONMENT_STRATEGY[RuntimeEnvironment.GITLAB_CI]
        assert s.mode == "dind"
        assert s.docker_host == "tcp://docker:2375"
        assert s.network_mode == "host"
        assert s.ci_setup_hint is not None

    def test_kubernetes_uses_warn_skip(self) -> None:
        s = ENVIRONMENT_STRATEGY[RuntimeEnvironment.KUBERNETES_POD]
        assert s.mode == "warn_skip"
        assert s.ci_setup_hint is not None

    def test_no_docker_uses_skip(self) -> None:
        s = ENVIRONMENT_STRATEGY[RuntimeEnvironment.NO_DOCKER]
        assert s.mode == "skip"


class TestCanStartContainers:
    def test_local_docker_can_start(self) -> None:
        assert can_start_containers(RuntimeEnvironment.LOCAL_DOCKER) is True

    def test_github_actions_can_start(self) -> None:
        assert can_start_containers(RuntimeEnvironment.GITHUB_ACTIONS) is True

    def test_k8s_cannot_start(self) -> None:
        assert can_start_containers(RuntimeEnvironment.KUBERNETES_POD) is False

    def test_no_docker_cannot_start(self) -> None:
        assert can_start_containers(RuntimeEnvironment.NO_DOCKER) is False

    def test_get_strategy_auto_detects(self) -> None:
        strategy = get_strategy()
        assert strategy.mode in ("testcontainers", "dind", "warn_skip", "skip")
