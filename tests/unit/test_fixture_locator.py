"""spec10 §4.4 / issue #143 — reuse the project's own conftest fixtures.

The failure being closed: on a project built around async SQLAlchemy,
`add_member(db: AsyncSession, team: Team, user_id: int)` became
`add_member(db=None, team=None, user_id=1)`, the guard raised AttributeError on
NoneType instead of the intended error, Gate 4 rejected the test, and `--fix`
reported 0-for-0 — while a `db_session` fixture sat unused in the project's
conftest.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quell.synthesis import fixture_locator, sig_inspector


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text(
        textwrap.dedent(
            '''
            import pytest

            @pytest.fixture
            def db_session() -> AsyncSession:
                """Real session the project already uses."""
                yield None

            @pytest.fixture()
            async def team_factory():
                yield None

            @pytest.fixture
            def unrelated_thing():
                return 1

            def not_a_fixture():
                return 2
            '''
        ).strip(),
        encoding="utf-8",
    )
    fixture_locator._find_fixtures_cached.cache_clear()
    return tmp_path


# ── discovery ────────────────────────────────────────────────────────────────


def test_discovers_fixtures_from_conftest(project: Path):
    found = fixture_locator.find_fixtures(project)
    assert set(found) == {"db_session", "team_factory", "unrelated_thing"}
    assert found["team_factory"].is_async is True
    assert found["db_session"].return_annotation == "AsyncSession"


def test_ignores_plain_functions_and_builtin_names(project: Path):
    found = fixture_locator.find_fixtures(project)
    assert "not_a_fixture" not in found
    # tmp_path etc. are pytest's own; a project fixture must never shadow them.
    assert not (set(found) & fixture_locator.BUILTIN_FIXTURES)


def test_missing_conftest_returns_empty_not_error(tmp_path: Path):
    fixture_locator._find_fixtures_cached.cache_clear()
    assert fixture_locator.find_fixtures(tmp_path) == {}


def test_malformed_conftest_does_not_raise(tmp_path: Path):
    (tmp_path / "conftest.py").write_text("def broken(:\n", encoding="utf-8")
    fixture_locator._find_fixtures_cached.cache_clear()
    assert fixture_locator.find_fixtures(tmp_path) == {}  # invariant #6


# ── resolution ───────────────────────────────────────────────────────────────


def test_resolves_by_exact_name(project: Path):
    fx = fixture_locator.find_fixtures(project)
    assert fixture_locator.resolve("db_session", None, fx) == "db_session"


def test_resolves_short_param_to_prefixed_fixture(project: Path):
    """`db: AsyncSession` should find `db_session`."""
    fx = fixture_locator.find_fixtures(project)
    assert fixture_locator.resolve("db", None, fx) == "db_session"


def test_resolves_by_return_annotation_type(project: Path):
    """Unhelpful param name, but the fixture's return type matches."""
    fx = fixture_locator.find_fixtures(project)
    assert fixture_locator.resolve("session_arg", "AsyncSession", fx) == "db_session"


def test_resolves_through_generic_and_module_path(project: Path):
    fx = fixture_locator.find_fixtures(project)
    assert (
        fixture_locator.resolve(
            "x", "Optional[sqlalchemy.ext.asyncio.AsyncSession]", fx
        )
        == "db_session"
    )


def test_returns_none_when_nothing_matches(project: Path):
    fx = fixture_locator.find_fixtures(project)
    assert fixture_locator.resolve("payment_gateway", "StripeClient", fx) is None


# ── integration with stub building ───────────────────────────────────────────


def test_stub_requests_fixture_instead_of_literal_none(project: Path, tmp_path: Path):
    """The regression this issue exists for: db=None becomes db=db_session."""
    src = project / "svc.py"
    src.write_text(
        "def add_member(db: AsyncSession, user_id: int):\n"
        "    if not db:\n"
        "        raise ValueError('no session')\n"
        "    return user_id\n",
        encoding="utf-8",
    )
    sig = sig_inspector.inspect("add_member", src)
    assert sig is not None

    without = sig_inspector.stub_for_call(sig)
    assert "db=None" in without[0]           # the old, broken behaviour
    assert "db_session" not in without[1]

    fx = fixture_locator.find_fixtures(project)
    args, fixtures, unknown = sig_inspector.stub_for_call(sig, fx)

    assert "db=db_session" in args
    assert "db_session" in fixtures
    assert "AsyncSession" not in unknown     # no longer an unresolved type
    assert "user_id=1" in args               # primitives still stubbed normally
