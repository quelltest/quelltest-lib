"""spec10 §4.4 rung 2 / issue #144 — build objects the way the project does.

Rung 1 (#143) covers parameters a conftest fixture supplies. This covers the
rest: a parameter typed `Team` with no matching fixture, where the repo already
constructs `Team(id=1, owner_id=42)` in a dozen places.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quell.synthesis import sig_inspector, usage_miner


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "models.py").write_text(
        textwrap.dedent(
            """
            class Team:
                def __init__(self, id, owner_id, plan="free"):
                    self.id = id
                    self.owner_id = owner_id
                    self.plan = plan

            class Wallet:
                def __init__(self, balance):
                    self.balance = balance
            """
        ).strip(),
        encoding="utf-8",
    )
    (tmp_path / "app" / "svc.py").write_text(
        textwrap.dedent(
            """
            from app.models import Team, Wallet

            def build():
                # literal args -- mineable
                return Team(id=1, owner_id=42, plan="pro")

            def build_wallet(db):
                # non-literal args -- must NOT be mined
                return Wallet(balance=db.lookup())
            """
        ).strip(),
        encoding="utf-8",
    )
    usage_miner._find_cached.cache_clear()
    return tmp_path


# ── mining ───────────────────────────────────────────────────────────────────


def test_mines_a_literal_construction_site(project: Path):
    found = usage_miner.find_constructions(project)
    assert "Team" in found
    assert found["Team"].call_args == "id=1, owner_id=42, plan='pro'"
    assert found["Team"].module == "app.models"


def test_skips_sites_with_non_literal_arguments(project: Path):
    """`Wallet(balance=db.lookup())` cannot be reused outside its context."""
    found = usage_miner.find_constructions(project)
    assert "Wallet" not in found


def test_expression_is_self_contained(project: Path):
    """No import plumbing needed by the caller."""
    expr = usage_miner.find_constructions(project)["Team"].expression()
    assert expr == (
        "__import__('app.models', fromlist=['Team'])"
        ".Team(id=1, owner_id=42, plan='pro')"
    )
    compile(expr, "<test>", "eval")  # must be valid Python


def test_resolve_handles_generics_and_module_paths(project: Path):
    found = usage_miner.find_constructions(project)
    for ann in ("Team", "app.models.Team", "Optional[Team]", "Team | None"):
        assert usage_miner.resolve(ann, found) is not None, ann


def test_resolve_returns_none_for_unknown_type(project: Path):
    found = usage_miner.find_constructions(project)
    assert usage_miner.resolve("StripeClient", found) is None
    assert usage_miner.resolve(None, found) is None


def test_empty_and_malformed_projects_do_not_raise(tmp_path: Path):
    usage_miner._find_cached.cache_clear()
    assert usage_miner.find_constructions(tmp_path) == {}

    (tmp_path / "broken.py").write_text("class (:\n", encoding="utf-8")
    usage_miner._find_cached.cache_clear()
    assert usage_miner.find_constructions(tmp_path) == {}  # invariant #6


def test_skips_heavy_directories(tmp_path: Path):
    """.venv must be pruned, not walked — see the 68s→683s regression in #143."""
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "vendored.py").write_text("class Vendored: pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("class Mine: pass\n", encoding="utf-8")
    usage_miner._find_cached.cache_clear()
    assert "Vendored" not in usage_miner.find_constructions(tmp_path)


# ── integration with stub building ───────────────────────────────────────────


def test_stub_uses_mined_construction_instead_of_none(project: Path):
    """The regression this rung exists for: team=None becomes a real Team."""
    src = project / "app" / "handlers.py"
    src.write_text(
        "from app.models import Team\n"
        "def promote(team: Team, user_id: int):\n"
        "    if not team.owner_id:\n"
        "        raise ValueError('no owner')\n"
        "    return user_id\n",
        encoding="utf-8",
    )
    sig = sig_inspector.inspect("promote", src)
    assert sig is not None

    before, _, unknown_before = sig_inspector.stub_for_call(sig)
    assert "team=None" in before
    assert any("Team" in u for u in unknown_before)

    usage_miner._find_cached.cache_clear()
    found = usage_miner.find_constructions(project)
    after, _, _ = sig_inspector.stub_for_call(sig, None, found)

    assert "team=None" not in after
    assert "owner_id=42" in after
    assert "user_id=1" in after  # primitives still stubbed normally


def test_fixture_wins_over_mined_construction(project: Path):
    """Rung 1 outranks rung 2 — a real fixture beats a reconstructed literal."""
    src = project / "app" / "handlers2.py"
    src.write_text(
        "from app.models import Team\n"
        "def promote(team: Team):\n"
        "    return team\n",
        encoding="utf-8",
    )
    sig = sig_inspector.inspect("promote", src)
    fixtures = {"team": object()}
    found = usage_miner.find_constructions(project)

    args, requested, _ = sig_inspector.stub_for_call(sig, fixtures, found)
    assert args == "team=team"
    assert requested == ["team"]
