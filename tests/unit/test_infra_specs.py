"""Tests for quell.infra.specs — security model and registry."""
from __future__ import annotations

import logging
import os

import pytest

from quell.infra.specs import (
    CONTAINER_SPECS,
    EPHEMERAL_CREDS,
    FORBIDDEN_ENV_READS,
    IMPORT_SIGNALS,
    INFRA_TYPE_NAMES,
    ContainerSpec,
    _assert_no_credential_reads,
    show_trust_message_once,
)


class TestForbiddenEnvGuard:
    def test_guard_logs_forbidden_key_but_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://real/prod")
        with caplog.at_level(logging.DEBUG, logger="quell.infra.specs"):
            _assert_no_credential_reads()
        assert any("DATABASE_URL" in r.message for r in caplog.records)

    def test_guard_covers_all_13_forbidden_names(self) -> None:
        assert len(FORBIDDEN_ENV_READS) == 13

    def test_guard_does_not_raise_when_env_is_clean(self) -> None:
        for key in FORBIDDEN_ENV_READS:
            os.environ.pop(key, None)
        _assert_no_credential_reads()  # must not raise


class TestEphemeralCreds:
    def test_all_five_services_present(self) -> None:
        assert set(EPHEMERAL_CREDS) == {"postgres", "redis", "mongo", "mysql", "localstack"}

    def test_postgres_creds_are_ephemeral_not_real(self) -> None:
        pg = EPHEMERAL_CREDS["postgres"]
        assert pg["user"] == "quell"
        assert pg["password"] == "quell_eph"
        assert pg["db"] == "quell_test"


class TestContainerSpecs:
    def test_all_seven_specs_present(self) -> None:
        assert set(CONTAINER_SPECS) == {
            "postgres", "redis", "localstack", "mongo", "smtp", "rabbitmq", "elasticsearch"
        }

    def test_each_spec_has_required_fields(self) -> None:
        for name, spec in CONTAINER_SPECS.items():
            assert isinstance(spec, ContainerSpec), name
            assert spec.image, name
            assert spec.port > 0, name
            assert "{host}" in spec.connection_url_template, name
            assert "{port}" in spec.connection_url_template, name

    def test_fixture_names_all_prefixed(self) -> None:
        for name, spec in CONTAINER_SPECS.items():
            assert spec.fixture_name.startswith("_quell_"), name


class TestImportSignals:
    def test_sqlalchemy_maps_to_postgres(self) -> None:
        assert IMPORT_SIGNALS["sqlalchemy"] == "postgres"

    def test_boto3_maps_to_localstack(self) -> None:
        assert IMPORT_SIGNALS["boto3"] == "localstack"

    def test_session_type_maps_to_postgres(self) -> None:
        assert INFRA_TYPE_NAMES["Session"] == "postgres"


class TestTrustMessage:
    def test_show_trust_message_once_creates_flag(self, tmp_path: pytest.TempPathFactory) -> None:
        import quell.infra.specs as specs_mod
        original = specs_mod._TRUST_FLAG
        flag = tmp_path / "trust_shown"  # type: ignore[operator]
        specs_mod._TRUST_FLAG = flag  # type: ignore[assignment]
        try:
            assert not flag.exists()
            show_trust_message_once()
            assert flag.exists()
            # second call must not raise
            show_trust_message_once()
        finally:
            specs_mod._TRUST_FLAG = original
