"""
Unit tests for quell.infra lockfile, resolver, fixture_gen, and engine.

All Docker calls are patched — no real containers are started.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from quell.infra.engine import ContainerEngine, ContainerSession
from quell.infra.fixture_gen import (
    _GUARD_END,
    _GUARD_START,
    generate_conftest_block,
    generate_fixture,
    inject_into_conftest,
)
from quell.infra.lockfile import (
    clear_lock,
    container_alive,
    read_lock,
    remove_lock_entry,
    stop_container,
    teardown_all,
    write_lock,
)
from quell.infra.resolver import resolve_specs, tags_from_import_signals
from quell.infra.specs import CONTAINER_SPECS
from quell.infra.specs import CONTAINER_SPECS as _SPECS


class TestReadLock:
    def test_missing_file_returns_empty(self, tmp_path):
        assert read_lock(tmp_path / "containers.lock") == {}

    def test_corrupt_json_returns_empty(self, tmp_path):
        p = tmp_path / "containers.lock"
        p.write_text("NOT JSON", encoding="utf-8")
        assert read_lock(p) == {}

    def test_reads_valid_json(self, tmp_path):
        p = tmp_path / "containers.lock"
        data = {"postgres": {"container_id": "abc123", "url": "postgres://..."}}
        p.write_text(json.dumps(data), encoding="utf-8")
        assert read_lock(p) == data


class TestWriteLock:
    def test_creates_parent_dir(self, tmp_path):
        lock = tmp_path / "sub" / "containers.lock"
        write_lock("redis", "cid1", "redis://localhost:6379", "redis:7", lock)
        assert lock.exists()

    def test_upserts_entry(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "cid1", "redis://localhost:6379", "redis:7", lock)
        write_lock("redis", "cid2", "redis://localhost:6380", "redis:7", lock)
        data = read_lock(lock)
        assert data["redis"]["container_id"] == "cid2"

    def test_preserves_other_entries(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("postgres", "pg1", "postgresql://...", "postgres:16", lock)
        write_lock("redis", "rd1", "redis://...", "redis:7", lock)
        data = read_lock(lock)
        assert "postgres" in data
        assert "redis" in data

    def test_atomic_write_no_partial(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "cid1", "redis://localhost", "redis:7", lock)
        # Verify no .tmp file left behind
        assert not (tmp_path / "containers.lock.tmp").exists()


class TestRemoveLockEntry:
    def test_removes_existing_entry(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "r1", "redis://...", "redis:7", lock)
        write_lock("postgres", "p1", "pg://...", "postgres:16", lock)
        remove_lock_entry("redis", lock)
        assert "redis" not in read_lock(lock)
        assert "postgres" in read_lock(lock)

    def test_removes_last_entry_deletes_file(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "r1", "redis://...", "redis:7", lock)
        remove_lock_entry("redis", lock)
        assert not lock.exists()

    def test_missing_key_is_noop(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "r1", "redis://...", "redis:7", lock)
        remove_lock_entry("postgres", lock)  # should not raise
        assert "redis" in read_lock(lock)


class TestClearLock:
    def test_deletes_file(self, tmp_path):
        lock = tmp_path / "containers.lock"
        lock.write_text("{}", encoding="utf-8")
        clear_lock(lock)
        assert not lock.exists()

    def test_noop_if_missing(self, tmp_path):
        clear_lock(tmp_path / "nonexistent.lock")  # should not raise


class TestContainerAlive:
    def test_running_container(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
            assert container_alive("abc123") is True

    def test_stopped_container(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="false\n")
            assert container_alive("abc123") is False

    def test_docker_error_returns_false(self):
        with patch("subprocess.run", side_effect=Exception("docker not found")):
            assert container_alive("abc123") is False

    def test_nonzero_returncode(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert container_alive("abc123") is False


class TestStopContainer:
    def test_stop_and_rm_called(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = stop_container("abc123")
        assert result is True
        assert mock_run.call_count == 2
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("stop" in cmd for cmd in cmds)
        assert any("rm" in cmd for cmd in cmds)

    def test_exception_returns_false(self):
        with patch("subprocess.run", side_effect=Exception("timeout")):
            assert stop_container("abc123") is False


class TestTeardownAll:
    def test_stops_all_containers(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "rid1", "redis://...", "redis:7", lock)
        write_lock("postgres", "pgid1", "pg://...", "postgres:16", lock)

        with patch("quell.infra.lockfile.stop_container", return_value=True) as mock_stop:
            torn = teardown_all(lock)

        assert set(torn) == {"redis", "postgres"}
        assert not lock.exists()
        assert mock_stop.call_count == 2

    def test_empty_lockfile_returns_empty(self, tmp_path):
        lock = tmp_path / "containers.lock"
        torn = teardown_all(lock)
        assert torn == []


# ---------------------------------------------------------------------------
# resolver
# ---------------------------------------------------------------------------


class TestResolveSpecs:
    def test_known_tags_resolved(self):
        specs = resolve_specs({"postgres", "redis"})
        tags = {s.tag for s in specs}
        assert "postgres" in tags
        assert "redis" in tags

    def test_unknown_tag_skipped(self):
        specs = resolve_specs({"postgres", "imaginary_db"})
        tags = {s.tag for s in specs}
        assert "imaginary_db" not in tags
        assert "postgres" in tags

    def test_empty_set_returns_empty(self):
        assert resolve_specs(set()) == []

    def test_deterministic_order(self):
        specs1 = resolve_specs({"redis", "postgres", "mongo"})
        specs2 = resolve_specs({"mongo", "redis", "postgres"})
        assert [s.tag for s in specs1] == [s.tag for s in specs2]


class TestTagsFromImportSignals:
    def test_basic_mapping(self):
        tags = tags_from_import_signals(["psycopg2", "redis"])
        assert "postgres" in tags
        assert "redis" in tags

    def test_celery_with_pika_removes_redis(self):
        tags = tags_from_import_signals(["celery", "pika"])
        assert "rabbitmq" in tags
        assert "redis" not in tags

    def test_celery_with_pika_and_direct_redis_keeps_redis(self):
        tags = tags_from_import_signals(["celery", "pika", "redis"])
        assert "rabbitmq" in tags
        assert "redis" in tags

    def test_celery_without_pika_keeps_redis(self):
        tags = tags_from_import_signals(["celery", "redis"])
        assert "redis" in tags

    def test_unknown_imports_ignored(self):
        tags = tags_from_import_signals(["numpy", "pandas"])
        assert tags == set()

    def test_custom_signals(self):
        custom = {"mydb": "postgres"}
        tags = tags_from_import_signals(["mydb"], import_signals=custom)
        assert "postgres" in tags


# ---------------------------------------------------------------------------
# fixture_gen
# ---------------------------------------------------------------------------


class TestGenerateFixture:
    def test_fixture_name_in_output(self):
        spec = CONTAINER_SPECS["redis"]
        src = generate_fixture(spec)
        assert spec.fixture_name in src

    def test_env_key_in_output(self):
        spec = CONTAINER_SPECS["postgres"]
        src = generate_fixture(spec)
        assert spec.connection_env_key in src

    def test_pytest_fixture_decorator(self):
        spec = CONTAINER_SPECS["redis"]
        src = generate_fixture(spec)
        assert "@pytest.fixture" in src

    def test_module_scope(self):
        spec = CONTAINER_SPECS["redis"]
        src = generate_fixture(spec)
        assert 'scope="module"' in src


class TestGenerateConftestBlock:
    def test_guard_comments_present(self):
        block = generate_conftest_block([CONTAINER_SPECS["redis"]])
        assert _GUARD_START in block
        assert _GUARD_END in block

    def test_multiple_specs_included(self):
        block = generate_conftest_block([CONTAINER_SPECS["redis"], CONTAINER_SPECS["postgres"]])
        assert CONTAINER_SPECS["redis"].fixture_name in block
        assert CONTAINER_SPECS["postgres"].fixture_name in block


class TestInjectIntoConftest:
    def test_appends_to_empty_file(self, tmp_path):
        conftest = tmp_path / "conftest.py"
        conftest.write_text("", encoding="utf-8")
        result = inject_into_conftest(str(conftest), [CONTAINER_SPECS["redis"]])
        assert _GUARD_START in result
        assert CONTAINER_SPECS["redis"].fixture_name in result

    def test_replaces_existing_block(self, tmp_path):
        conftest = tmp_path / "conftest.py"
        old_block = f"{_GUARD_START}\n# old content\n{_GUARD_END}\n"
        conftest.write_text(old_block, encoding="utf-8")
        result = inject_into_conftest(str(conftest), [CONTAINER_SPECS["postgres"]])
        assert "# old content" not in result
        assert CONTAINER_SPECS["postgres"].fixture_name in result

    def test_nonexistent_file_creates_content(self, tmp_path):
        conftest = tmp_path / "conftest.py"
        result = inject_into_conftest(str(conftest), [CONTAINER_SPECS["redis"]])
        assert _GUARD_START in result

    def test_existing_user_code_preserved(self, tmp_path):
        conftest = tmp_path / "conftest.py"
        user_code = "import os\n\ndef my_fixture(): pass\n"
        conftest.write_text(user_code, encoding="utf-8")
        result = inject_into_conftest(str(conftest), [CONTAINER_SPECS["redis"]])
        assert "def my_fixture" in result
        assert "import os" in result


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------


class TestContainerSession:
    def test_register_and_get(self):
        s = ContainerSession()
        s.register("redis", "redis://localhost:6379")
        assert s.get_url("redis") == "redis://localhost:6379"

    def test_get_unknown_returns_none(self):
        s = ContainerSession()
        assert s.get_url("postgres") is None

    def test_env_vars_includes_rollback_flag(self):
        s = ContainerSession()
        s.register("redis", "redis://localhost:6379")
        env = s.env_vars
        assert env.get("QUELL_TRANSACTION_ROLLBACK") == "true"

    def test_env_vars_includes_connection_url(self):
        s = ContainerSession()
        s.register("redis", "redis://localhost:6379")
        env = s.env_vars
        spec = _SPECS["redis"]
        assert env.get(spec.connection_env_key) == "redis://localhost:6379"

    def test_tags_property(self):
        s = ContainerSession()
        s.register("redis", "redis://localhost:6379")
        s.register("postgres", "postgresql://localhost:5432/quell")
        assert s.tags == {"redis", "postgres"}


class TestContainerEnginePrepare:
    def test_empty_tags_returns_empty_session(self, tmp_path):
        engine = ContainerEngine(lock_path=tmp_path / "containers.lock")
        session = engine.prepare(set())
        assert session.tags == set()

    def test_reuses_alive_container(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "existing_cid", "redis://localhost:6380", "redis:7", lock)

        engine = ContainerEngine(lock_path=lock)
        with patch("quell.infra.engine.container_alive", return_value=True):
            session = engine.prepare({"redis"})

        assert session.get_url("redis") == "redis://localhost:6380"

    def test_starts_new_when_not_alive(self, tmp_path):
        lock = tmp_path / "containers.lock"
        engine = ContainerEngine(lock_path=lock)

        with (
            patch("quell.infra.engine.container_alive", return_value=False),
            patch.object(engine, "_start", return_value="redis://localhost:9999") as mock_start,
            patch("quell.infra.specs.show_trust_message_once"),
        ):
            session = engine.prepare({"redis"})

        mock_start.assert_called_once()
        assert session.get_url("redis") == "redis://localhost:9999"

    def test_unknown_tag_skipped(self, tmp_path):
        lock = tmp_path / "containers.lock"
        engine = ContainerEngine(lock_path=lock)
        with patch("quell.infra.specs.show_trust_message_once"):
            session = engine.prepare({"does_not_exist"})
        assert session.tags == set()


class TestContainerEngineTeardown:
    def test_teardown_all_when_tags_none(self, tmp_path):
        lock = tmp_path / "containers.lock"
        engine = ContainerEngine(lock_path=lock)
        with patch("quell.infra.engine.teardown_all", return_value=["redis"]) as mock_td:
            result = engine.teardown()
        mock_td.assert_called_once_with(lock)
        assert result == ["redis"]

    def test_teardown_specific_tags(self, tmp_path):
        lock = tmp_path / "containers.lock"
        write_lock("redis", "rid1", "redis://...", "redis:7", lock)
        engine = ContainerEngine(lock_path=lock)

        with patch("quell.infra.engine.container_alive", return_value=True), \
             patch("quell.infra.engine.stop_container", return_value=True) as mock_stop:
            result = engine.teardown({"redis"})

        mock_stop.assert_called_once_with("rid1")
        assert "redis" in result
