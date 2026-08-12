"""
Detects how a project runs async tests, so generated tests match it.
(spec10 §4.4 rung 4, issue #146)

Why this exists
---------------
The rule engine wrapped every async target in `asyncio.run(...)`:

    def test_x():
        with pytest.raises(Exception):
            asyncio.run(add_member(db=db_session))

That works only for a bare coroutine called with literal arguments. It breaks
the moment the project uses pytest-asyncio or anyio, because:

  * `db_session` is an *async* fixture — under asyncio.run it is an unawaited
    async generator, not a session;
  * asyncio.run creates a NEW event loop, so any object bound to the fixture's
    loop (an AsyncSession, an engine, a connection pool) raises
    "attached to a different loop";
  * an async fixture requested by a sync test is never awaited at all.

So #143 (reuse the project's db_session fixture) is inert on exactly the
codebases it was built for unless the test is itself `async def`. This module
is what makes that pairing work.

Detection is conservative: if no async plugin is found we keep asyncio.run,
which is the pre-existing behaviour. Follows invariant #6 — never raises.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class AsyncStyle:
    """How this project expects an async test to be written."""

    plugin: str          # "asyncio" | "anyio" | "none"
    needs_marker: bool   # False under asyncio_mode = "auto"

    @property
    def supported(self) -> bool:
        """True when we can emit a native `async def` test."""
        return self.plugin != "none"

    @property
    def marker(self) -> str:
        """Decorator line to prepend, or '' when none is required."""
        if not self.needs_marker or self.plugin == "none":
            return ""
        return f"@pytest.mark.{self.plugin}\n"


NO_ASYNC = AsyncStyle(plugin="none", needs_marker=False)


def detect(project_root: Path) -> AsyncStyle:
    """Return the project's async test style, or NO_ASYNC if none is found."""
    try:
        return _detect_cached(str(project_root.resolve()))
    except Exception:  # noqa: BLE001 — invariant #6
        return NO_ASYNC


@lru_cache(maxsize=32)
def _detect_cached(root_str: str) -> AsyncStyle:
    root = Path(root_str)
    pyproject = root / "pyproject.toml"

    text = ""
    cfg: dict = {}
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
            cfg = tomllib.loads(text)
        except Exception:  # noqa: BLE001
            cfg = {}

    ini = cfg.get("tool", {}).get("pytest", {}).get("ini_options", {})
    mode = str(ini.get("asyncio_mode", "")).strip().lower()

    # Legacy config files carry the same keys.
    for name in ("pytest.ini", "setup.cfg", "tox.ini"):
        if mode:
            break
        f = root / name
        if not f.exists():
            continue
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        text += raw
        m = re.search(r"^\s*asyncio_mode\s*=\s*(\w+)", raw, re.M)
        if m:
            mode = m.group(1).lower()

    if mode in ("auto", "strict"):
        # auto mode marks async tests automatically; strict needs the decorator.
        return AsyncStyle(plugin="asyncio", needs_marker=(mode == "strict"))

    if _mentions(text, "pytest-asyncio") or _mentions(text, "pytest_asyncio"):
        # Installed but unconfigured ⇒ pytest-asyncio defaults to strict.
        return AsyncStyle(plugin="asyncio", needs_marker=True)

    if _mentions(text, "anyio"):
        return AsyncStyle(plugin="anyio", needs_marker=True)

    return NO_ASYNC


def _mentions(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


# ── code rewriting ───────────────────────────────────────────────────────────

_ASYNCIO_RUN = re.compile(r"asyncio\.run\((?P<inner>.+)\)(?P<trailer>\s*)$")


def to_async_test(code: str, style: AsyncStyle) -> str:
    """Rewrite a generated sync test into a native async test.

    `def test_x(...)`      → `async def test_x(...)`, with the marker if needed
    `asyncio.run(expr)`    → `await expr`
    the now-unused `import asyncio` is dropped

    Returns `code` unchanged when the project has no async plugin, so projects
    without one keep the previous asyncio.run behaviour.
    """
    if not style.supported or "asyncio.run(" not in code:
        return code

    out: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()

        if stripped.startswith("def test_"):
            out.append(f"async {line.lstrip()}" if not line.startswith(" ") else f"async {line}")
            continue

        if stripped == "import asyncio":
            continue  # no longer referenced once asyncio.run is gone

        m = _ASYNCIO_RUN.search(line)
        if m:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}await {m.group('inner')}{m.group('trailer')}")
            continue

        out.append(line)

    return style.marker + "\n".join(out) + ("\n" if code.endswith("\n") else "")
