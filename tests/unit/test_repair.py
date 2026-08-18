"""spec10 §4.4 / issue #147 — read the failure instead of discarding it.

The pipeline was generate -> verify -> discard. The stack trace naming exactly
what was wrong was captured and then thrown away. Every comparable system runs
generate -> execute -> feed the error back -> repair; TestGen-LLM at Meta
(arXiv 2402.09171) shows the value comes from the loop *plus* the filter.

Error strings below are real pytest output shapes, not paraphrases -- a
classifier tested against invented text proves nothing about production logs.
"""
from __future__ import annotations

import pytest

from quell.core.repair import FailureCause, RepairStrategy, diagnose

NONE_ATTR = """
    def test_quell_add_member_not_null_ab12(db_session):
        with pytest.raises(Exception):
>           add_member(db=None, team=None, user_id=1)
E           AttributeError: 'NoneType' object has no attribute 'owner_id'
tests/test_teams.py:8: AttributeError
"""

NO_FIXTURE = """
E       fixture 'db_session' not found
>       available fixtures: anyio_backend, cache, capfd, capsys, doctest_namespace
>       use 'pytest --fixtures [testpath]' for help on them.
"""

NAME_ERROR = """
>       team = Team(id=1)
E       NameError: name 'Team' is not defined
"""

MODULE_ERROR = """
ImportError while importing test module '/tmp/test__quell_tmp_ab.py'.
E   ModuleNotFoundError: No module named 'app'
"""

SIGNATURE = """
>       add_member(db=db_session)
E       TypeError: add_member() missing 2 required positional arguments: 'team' and 'user_id'
"""

UNEXPECTED_KWARG = """
>       rename_team(db=db_session, value="x")
E       TypeError: rename_team() got an unexpected keyword argument 'value'
"""

SYNTAX = """
ERROR collecting tests/test__quell_tmp_cd.py
E   SyntaxError: invalid syntax
"""

ASSERTION = """
>       assert result is not None
E       assert None is not None
"""


# ── classification ───────────────────────────────────────────────────────────


def test_none_stub_attribute_routes_to_guard_mock():
    """The signature failure of the pre-#143 stub strategy."""
    d = diagnose(NONE_ATTR)
    assert d.cause is FailureCause.NONE_STUB_ATTRIBUTE
    assert d.strategy is RepairStrategy.USE_GUARD_MOCK
    assert d.subject == "owner_id"       # the attribute the mock must supply
    assert d.is_repairable


def test_missing_fixture_routes_to_construction():
    """fixture_locator false positive — fall back to building the value."""
    d = diagnose(NO_FIXTURE)
    assert d.cause is FailureCause.MISSING_FIXTURE
    assert d.strategy is RepairStrategy.USE_MINED_CONSTRUCTION
    assert d.subject == "db_session"


@pytest.mark.parametrize("text", [NAME_ERROR, MODULE_ERROR])
def test_unresolved_names_route_to_import_fix(text: str):
    d = diagnose(text)
    assert d.cause is FailureCause.MISSING_IMPORT
    assert d.strategy is RepairStrategy.FIX_IMPORT
    assert d.subject in {"Team", "app"}


@pytest.mark.parametrize("text", [SIGNATURE, UNEXPECTED_KWARG])
def test_signature_errors_route_to_reinspection(text: str):
    d = diagnose(text)
    assert d.cause is FailureCause.SIGNATURE_MISMATCH
    assert d.strategy is RepairStrategy.REINSPECT_SIGNATURE


# ── knowing when to stop ─────────────────────────────────────────────────────


def test_syntax_error_is_not_repairable():
    """A file pytest cannot parse is a generator bug, not an argument problem."""
    d = diagnose(SYNTAX)
    assert d.cause is FailureCause.COLLECTION_ERROR
    assert d.is_repairable is False


def test_plain_assertion_failure_is_not_repairable():
    """The test ran and the assertion was wrong — no rung fixes that."""
    d = diagnose(ASSERTION)
    assert d.cause is FailureCause.UNKNOWN
    assert d.strategy is RepairStrategy.GIVE_UP


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_input_gives_up_rather_than_guessing(text):
    """Retrying blind burns two pytest runs per attempt for nothing."""
    assert diagnose(text).is_repairable is False


def test_every_cause_has_a_distinct_strategy():
    """A cause with no strategy would loop forever without progress."""
    seen = {
        diagnose(t).cause: diagnose(t).strategy
        for t in (NONE_ATTR, NO_FIXTURE, NAME_ERROR, SIGNATURE, SYNTAX, ASSERTION)
    }
    repairable = {c: s for c, s in seen.items() if s is not RepairStrategy.GIVE_UP}
    assert len(set(repairable.values())) == len(repairable)


def test_most_specific_pattern_wins():
    """A NoneType attribute error inside a longer trace still classifies."""
    noisy = SIGNATURE + NONE_ATTR + ASSERTION
    assert diagnose(noisy).cause is FailureCause.NONE_STUB_ATTRIBUTE


# ── applying a repair ────────────────────────────────────────────────────────

FAILED_TEST = '''def test_quell_add_member_not_null_ab12():
    """Quell: team must have an owner"""
    import pytest
    from app.teams import add_member
    with pytest.raises(Exception):
        add_member(db=None, team=None, user_id=1)
'''


def test_repair_targets_the_parameter_the_guard_reads():
    """`owner_id` belongs to `team`, not to the first None argument.

    pytest names the attribute but not its owner. Swapping the first `=None`
    would mock `db` and leave the real failure untouched — an identical second
    failure. The guard source names the owner.
    """
    from quell.core.repair import attempt_repair

    repaired = attempt_repair(
        FAILED_TEST, diagnose(NONE_ATTR), guard_text="if not team.owner_id:"
    )
    assert repaired is not None
    assert "db=None" in repaired            # untouched
    assert "team=None" not in repaired      # replaced
    assert "MagicMock(owner_id=None)" in repaired
    compile(repaired, "<t>", "exec")


def test_declines_when_the_owner_is_ambiguous():
    """Two None args and no guard text ⇒ decline rather than swap blind."""
    from quell.core.repair import attempt_repair

    assert attempt_repair(FAILED_TEST, diagnose(NONE_ATTR)) is None


def test_single_none_argument_is_unambiguous():
    from quell.core.repair import attempt_repair

    code = "def test_x():\n    handle(team=None)\n"
    repaired = attempt_repair(code, diagnose(NONE_ATTR))
    assert repaired is not None
    assert "MagicMock(owner_id=None)" in repaired


def test_repaired_mock_keeps_the_guard_firing():
    """A bare MagicMock is truthy and would silently stop `if not x.attr:`."""
    mock = eval(  # noqa: S307
        "__import__('unittest.mock', fromlist=['MagicMock']).MagicMock(owner_id=None)"
    )
    assert not mock.owner_id


def test_repair_drops_an_unavailable_fixture():
    from quell.core.repair import Diagnosis, FailureCause, RepairStrategy, attempt_repair

    code = "def test_x(db_session, tmp_path):\n    assert True\n"
    d = Diagnosis(FailureCause.MISSING_FIXTURE, RepairStrategy.DROP_FIXTURE, "db_session")
    repaired = attempt_repair(code, d)
    assert repaired == "def test_x(tmp_path):\n    assert True\n"


def test_unrepairable_diagnosis_returns_none():
    from quell.core.repair import attempt_repair

    assert attempt_repair(FAILED_TEST, diagnose(SYNTAX)) is None
    assert attempt_repair(FAILED_TEST, diagnose(ASSERTION)) is None
    assert attempt_repair("", diagnose(NONE_ATTR)) is None


def test_repair_never_returns_invalid_python():
    from quell.core.repair import attempt_repair

    for code in (FAILED_TEST, "x=None", "def test_a(): pass"):
        out = attempt_repair(code, diagnose(NONE_ATTR), guard_text="if not team.owner_id:")
        if out is not None:
            compile(out, "<t>", "exec")
