"""
Generate pytest fixture source code for ephemeral containers.

Each ContainerSpec produces a module-scoped pytest fixture that:
  - Yields the connection URL
  - Is prefixed with _quell_ to avoid collisions with user fixtures
  - Is guarded by a comment block so it's identifiable in conftest.py
"""
from __future__ import annotations

from quell.infra.specs import ContainerSpec

_GUARD_START = "# --- quelltest generated fixtures (do not edit) ---"
_GUARD_END = "# --- end quelltest generated fixtures ---"


def generate_fixture(spec: ContainerSpec) -> str:
    """Return pytest fixture source code for one ContainerSpec."""
    imports = "\n".join(spec.extra_imports)
    env_key = spec.connection_env_key
    fixture_name = spec.fixture_name

    return f'''\
{imports}

@pytest.fixture(scope="module")
def {fixture_name}():
    """Ephemeral {spec.tag} container — quelltest managed, throwaway credentials."""
    import os
    url = os.environ.get("{env_key}", "")
    if not url:
        pytest.skip("No {env_key} set — quelltest container not started")
    yield url
'''


def generate_conftest_block(specs: list[ContainerSpec]) -> str:
    """Return a full conftest.py block for the given specs, with guard comments."""
    fixtures = "\n\n".join(generate_fixture(s) for s in specs)
    return f"""\
{_GUARD_START}
import pytest

{fixtures}
{_GUARD_END}
"""


def inject_into_conftest(conftest_path: str, specs: list[ContainerSpec]) -> str:
    """
    Insert or replace the quelltest fixture block in an existing conftest.py.

    If the guard is already present, replaces the block. Otherwise appends it.
    Returns the new file content (does not write to disk).
    """
    from pathlib import Path

    path = Path(conftest_path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    block = generate_conftest_block(specs)

    if _GUARD_START in existing:
        # Replace existing block
        start = existing.index(_GUARD_START)
        end = existing.index(_GUARD_END) + len(_GUARD_END)
        return existing[:start] + block + existing[end:]

    # Check for name collision before appending
    for spec in specs:
        if spec.fixture_name in existing:
            # # TODO(spec): collision detection should warn via CLI, not raise
            pass

    return existing.rstrip("\n") + "\n\n" + block + "\n"
