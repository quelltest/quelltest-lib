"""spec10 §4.4 / issue #146 — generate native async tests, not asyncio.run().

Why this matters beyond tidiness: #143 made generated tests request the
project's real `db_session` fixture, but under `asyncio.run(...)` that fixture
is either never awaited or bound to a different event loop than the object
under test. The two changes only pay off together.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quell.synthesis import async_style

SYNC_TEST = textwrap.dedent(
    '''
    def test_quell_add_member_not_null_abc123(db_session):
        """Quell: db must not be None"""
        import asyncio
        import pytest
        from app.svc import add_member
        with pytest.raises(Exception):
            asyncio.run(add_member(db=db_session, user_id=1))
    '''
).lstrip()


def _project(tmp_path: Path, pyproject: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent(pyproject), encoding="utf-8")
    async_style._detect_cached.cache_clear()
    return tmp_path


# ── detection ────────────────────────────────────────────────────────────────


def test_detects_asyncio_auto_mode_needs_no_marker(tmp_path: Path):
    root = _project(tmp_path, """
        [tool.pytest.ini_options]
        asyncio_mode = "auto"
    """)
    style = async_style.detect(root)
    assert style.plugin == "asyncio"
    assert style.needs_marker is False
    assert style.marker == ""


def test_detects_strict_mode_requires_marker(tmp_path: Path):
    root = _project(tmp_path, """
        [tool.pytest.ini_options]
        asyncio_mode = "strict"
    """)
    style = async_style.detect(root)
    assert style.needs_marker is True
    assert style.marker == "@pytest.mark.asyncio\n"


def test_installed_but_unconfigured_defaults_to_strict(tmp_path: Path):
    """pytest-asyncio's own default is strict, so a marker is required."""
    root = _project(tmp_path, """
        [project]
        dependencies = ["pytest-asyncio>=0.23"]
    """)
    style = async_style.detect(root)
    assert style.plugin == "asyncio"
    assert style.needs_marker is True


def test_detects_anyio(tmp_path: Path):
    root = _project(tmp_path, """
        [project]
        dependencies = ["anyio"]
    """)
    assert async_style.detect(root).marker == "@pytest.mark.anyio\n"


def test_no_plugin_is_unsupported(tmp_path: Path):
    root = _project(tmp_path, """
        [project]
        dependencies = ["requests"]
    """)
    style = async_style.detect(root)
    assert style.supported is False


def test_missing_and_malformed_pyproject_do_not_raise(tmp_path: Path):
    async_style._detect_cached.cache_clear()
    assert async_style.detect(tmp_path) is async_style.NO_ASYNC

    (tmp_path / "pyproject.toml").write_text("[[[not toml", encoding="utf-8")
    async_style._detect_cached.cache_clear()
    assert async_style.detect(tmp_path).supported is False  # invariant #6


def test_reads_legacy_pytest_ini(tmp_path: Path):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nasyncio_mode = auto\n", encoding="utf-8"
    )
    async_style._detect_cached.cache_clear()
    assert async_style.detect(tmp_path).plugin == "asyncio"


# ── rewriting ────────────────────────────────────────────────────────────────


def test_rewrites_to_native_async_test():
    style = async_style.AsyncStyle(plugin="asyncio", needs_marker=False)
    out = async_style.to_async_test(SYNC_TEST, style)

    assert out.startswith("async def test_quell_add_member")
    assert "await add_member(db=db_session, user_id=1)" in out
    assert "asyncio.run" not in out
    assert "import asyncio" not in out       # dropped, now unreferenced
    assert "import pytest" in out            # still needed for pytest.raises
    assert "with pytest.raises(Exception):" in out


def test_adds_marker_in_strict_mode():
    style = async_style.AsyncStyle(plugin="asyncio", needs_marker=True)
    out = async_style.to_async_test(SYNC_TEST, style)
    assert out.startswith("@pytest.mark.asyncio\nasync def test_")


def test_preserves_indentation_of_awaited_call():
    style = async_style.AsyncStyle(plugin="asyncio", needs_marker=False)
    out = async_style.to_async_test(SYNC_TEST, style)
    await_line = next(ln for ln in out.splitlines() if "await " in ln)
    assert await_line.startswith("        ")   # inside `with`, 8 spaces


def test_output_is_valid_python():
    import ast

    for needs_marker in (False, True):
        style = async_style.AsyncStyle(plugin="asyncio", needs_marker=needs_marker)
        ast.parse(async_style.to_async_test(SYNC_TEST, style))


def test_unchanged_when_project_has_no_async_plugin():
    """Projects without a plugin keep the previous asyncio.run behaviour."""
    assert async_style.to_async_test(SYNC_TEST, async_style.NO_ASYNC) == SYNC_TEST


def test_sync_test_untouched():
    sync = "def test_x():\n    assert foo() == 1\n"
    style = async_style.AsyncStyle(plugin="asyncio", needs_marker=True)
    assert async_style.to_async_test(sync, style) == sync


@pytest.mark.parametrize("plugin", ["asyncio", "anyio"])
def test_marker_matches_plugin(plugin: str):
    style = async_style.AsyncStyle(plugin=plugin, needs_marker=True)
    assert async_style.to_async_test(SYNC_TEST, style).startswith(
        f"@pytest.mark.{plugin}\n"
    )
