"""
Classifies why a generated test failed Gate 4, so the engine can retry.
(spec10 §4.4, issue #147)

Why this exists
---------------
The pipeline was generate -> verify -> discard. A rejected test yielded zero
information: the stack trace naming exactly what was wrong was captured into
`error_message` and then thrown away.

Every comparable system runs generate -> execute -> feed the error back ->
repair, capped at a few attempts. TestGen-LLM at Meta (arXiv 2402.09171)
reports 75% built / 57% reliably passing / 25% coverage-improving -- the value
comes from the loop *plus* the filter, not the filter alone. quelltest built
the filter and skipped the loop.

This module is the "read the error" half. It does not repair anything itself;
it names the cause and the strategy that addresses it, so the caller can retry
with a different rung of the §4.4 ladder instead of guessing.

Deliberately conservative: an unrecognised failure returns UNKNOWN and the
caller discards as before. Retrying blind would burn two pytest runs per
attempt for nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class FailureCause(StrEnum):
    """What actually went wrong, read out of pytest's output."""

    NONE_STUB_ATTRIBUTE = "a None stub was passed where an object was needed"
    MISSING_FIXTURE = "the test requested a fixture that does not exist"
    MISSING_IMPORT = "a name in the test could not be resolved"
    SIGNATURE_MISMATCH = "the call did not match the function signature"
    COLLECTION_ERROR = "pytest could not collect the test file"
    UNKNOWN = "cause not recognised"


class RepairStrategy(StrEnum):
    """Which §4.4 rung to try next."""

    USE_GUARD_MOCK = "retry with a guard-aware mock for the failing parameter"
    USE_MINED_CONSTRUCTION = "retry with a mined construction site"
    DROP_FIXTURE = "retry without the unavailable fixture"
    FIX_IMPORT = "retry with the missing import resolved"
    REINSPECT_SIGNATURE = "re-read the signature and rebuild the call"
    GIVE_UP = "no strategy addresses this failure"


@dataclass(frozen=True)
class Diagnosis:
    """A classified failure plus what to do about it."""

    cause: FailureCause
    strategy: RepairStrategy
    #  The parameter or name the error implicates, when the text reveals it.
    subject: str | None = None

    @property
    def is_repairable(self) -> bool:
        return self.strategy is not RepairStrategy.GIVE_UP


_GIVE_UP = Diagnosis(FailureCause.UNKNOWN, RepairStrategy.GIVE_UP)

# `AttributeError: 'NoneType' object has no attribute 'owner_id'`
_NONE_ATTR = re.compile(
    r"AttributeError:\s*'NoneType' object has no attribute '(?P<attr>\w+)'"
)
# `fixture 'db_session' not found`
_NO_FIXTURE = re.compile(r"fixture '(?P<name>[\w-]+)' not found")
# `NameError: name 'Team' is not defined`
_NAME_ERROR = re.compile(r"NameError:\s*name '(?P<name>\w+)' is not defined")
# `ModuleNotFoundError: No module named 'app'` / `ImportError: cannot import name 'X'`
_IMPORT_ERROR = re.compile(
    r"(?:ModuleNotFoundError: No module named '(?P<mod>[\w.]+)'"
    r"|ImportError: cannot import name '(?P<name>\w+)')"
)
# `TypeError: f() missing 2 required positional arguments: 'a' and 'b'`
# `TypeError: f() got an unexpected keyword argument 'x'`
_SIGNATURE = re.compile(
    r"TypeError:.*?(?:missing \d+ required positional argument"
    r"|got an unexpected keyword argument '(?P<kw>\w+)'"
    r"|takes \d+ positional argument)"
)
_COLLECT = re.compile(r"(?:ERROR collecting|INTERNALERROR|SyntaxError:)")


def diagnose(error_text: str | None) -> Diagnosis:
    """Read pytest output and name the cause plus the strategy to try next.

    Order matters: the most specific and most actionable patterns are checked
    first. A NoneType attribute error is the signature failure of the pre-#143
    stub strategy and has a direct fix, so it outranks the generic ones.
    """
    if not error_text:
        return _GIVE_UP
    text = error_text

    m = _NONE_ATTR.search(text)
    if m:
        # The guard read an attribute off a parameter we stubbed as None.
        # A guard-aware mock (#145) supplies exactly that attribute.
        return Diagnosis(
            FailureCause.NONE_STUB_ATTRIBUTE,
            RepairStrategy.USE_GUARD_MOCK,
            subject=m.group("attr"),
        )

    m = _NO_FIXTURE.search(text)
    if m:
        # We asked for a fixture the project does not actually provide here --
        # a fixture_locator false positive. Fall back to constructing the value.
        return Diagnosis(
            FailureCause.MISSING_FIXTURE,
            RepairStrategy.USE_MINED_CONSTRUCTION,
            subject=m.group("name"),
        )

    m = _SIGNATURE.search(text)
    if m:
        return Diagnosis(
            FailureCause.SIGNATURE_MISMATCH,
            RepairStrategy.REINSPECT_SIGNATURE,
            subject=m.group("kw"),
        )

    m = _NAME_ERROR.search(text)
    if m:
        return Diagnosis(
            FailureCause.MISSING_IMPORT,
            RepairStrategy.FIX_IMPORT,
            subject=m.group("name"),
        )

    m = _IMPORT_ERROR.search(text)
    if m:
        return Diagnosis(
            FailureCause.MISSING_IMPORT,
            RepairStrategy.FIX_IMPORT,
            subject=m.group("mod") or m.group("name"),
        )

    if _COLLECT.search(text):
        # A file pytest cannot even parse is a generator bug, not something a
        # different argument strategy would fix.
        return Diagnosis(FailureCause.COLLECTION_ERROR, RepairStrategy.GIVE_UP)

    return _GIVE_UP


# ── applying a repair ────────────────────────────────────────────────────────


def attempt_repair(
    test_code: str,
    diagnosis: Diagnosis,
    guard_text: str | None = None,
) -> str | None:
    """Rewrite a failed test according to the diagnosis, or None if we can't.

    Rewrites the generated source directly rather than regenerating through the
    engine. That keeps the loop self-contained: no new parameter has to be
    threaded through eight per-kind generators just to force one rung, and the
    repaired test is verified by exactly the same gates as the original.

    Returns None whenever the rewrite would be a guess. A repair that cannot be
    made precisely is worse than a discard, because it costs two more pytest
    runs and can turn a clean rejection into a test that passes for the wrong
    reason.
    """
    if not diagnosis.is_repairable or not test_code:
        return None

    if diagnosis.strategy is RepairStrategy.USE_GUARD_MOCK and diagnosis.subject:
        return _swap_none_for_mock(test_code, diagnosis.subject, guard_text)

    if diagnosis.strategy is RepairStrategy.DROP_FIXTURE and diagnosis.subject:
        return _drop_fixture(test_code, diagnosis.subject)

    # REINSPECT_SIGNATURE / FIX_IMPORT / USE_MINED_CONSTRUCTION need generator
    # context this function does not have. Named by diagnose() so the report can
    # explain the rejection, but not yet automated.
    return None


def _swap_none_for_mock(
    test_code: str,
    attr: str,
    guard_text: str | None = None,
) -> str | None:
    """Replace the *right* `<param>=None` with a mock exposing `attr`.

    The guard read `<param>.<attr>` off a None stub. A MagicMock with that
    attribute set to None satisfies the access *and* keeps the guard firing --
    a bare MagicMock would be truthy and silently stop it (see guard_mock).

    Which parameter to swap matters. pytest's AttributeError names the
    attribute (`owner_id`) but not its owner, and in
    `add_member(db=None, team=None, user_id=1)` the guard reads
    `team.owner_id` -- swapping the first `=None` would mock `db`, leave the
    real failure untouched, and produce an identical second failure. The
    guard source names the owner, so it is parsed when available. Without it,
    a single None argument is unambiguous; more than one and we decline
    rather than swap blind.
    """
    param: str | None = None
    if guard_text:
        try:
            from quell.synthesis import guard_mock

            parsed = guard_mock.parse_guard(guard_text)
            if parsed is not None and parsed.attr == attr:
                param = parsed.obj
        except Exception:  # noqa: BLE001 - fall through to the count check
            param = None

    if param is not None:
        m = re.search(r"\b(?P<param>" + re.escape(param) + r")=None\b", test_code)
    elif len(re.findall(r"\b\w+=None\b", test_code)) == 1:
        m = re.search(r"\b(?P<param>\w+)=None\b", test_code)
    else:
        return None
    if m is None:
        return None

    mock = (
        "__import__('unittest.mock', fromlist=['MagicMock'])"
        f".MagicMock({attr}=None)"
    )
    repaired = test_code[: m.start()] + f"{m.group('param')}={mock}" + test_code[m.end():]
    try:
        compile(repaired, "<repair>", "exec")
    except SyntaxError:
        return None
    return repaired


def _drop_fixture(test_code: str, fixture: str) -> str | None:
    """Remove an unavailable fixture from the test's parameter list."""
    pattern = re.compile(
        r"(def\s+test_\w+\()(?P<params>[^)]*)(\))"
    )
    m = pattern.search(test_code)
    if m is None:
        return None
    params = [p.strip() for p in m.group("params").split(",") if p.strip()]
    kept = [p for p in params if p != fixture]
    if len(kept) == len(params):
        return None
    repaired = pattern.sub(lambda _m: f"{_m.group(1)}{', '.join(kept)}{_m.group(3)}", test_code, count=1)
    try:
        compile(repaired, "<repair>", "exec")
    except SyntaxError:
        return None
    return repaired
