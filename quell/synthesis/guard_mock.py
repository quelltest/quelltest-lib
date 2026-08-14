"""
Guard-aware mocks for parameters no fixture or construction site can supply.
(spec10 §4.4 rung 3, issue #145)

The trap this exists to avoid
-----------------------------
The obvious implementation of this rung is wrong:

    team = MagicMock(spec=Team)
    if not team.owner_id:      # owner_id is a Mock -> truthy -> guard NEVER fires
        raise ValueError(...)

Every attribute of a plain MagicMock is another Mock, and Mocks are truthy. A
mock passed to a `if not x.attr:` guard makes that guard stop firing, so the
generated test exercises nothing. It would still pass Gate 4 — for entirely the
wrong reason — and be rejected by Gate 5, silently costing two pytest runs per
candidate. Worse, for a guard whose violating value is truthy, it could produce
a test that passes while asserting nothing.

So the mock must know which attribute the guard reads and what value violates
it. `MagicMock(spec=Team, owner_id=None)` sets `.owner_id` to None directly —
MagicMock's constructor kwargs configure attributes — and the guard fires.

This rung sits BELOW fixtures (#143) and mined constructions (#144). A real
object carries invariants a mock does not; the mock is the fallback for
parameters nothing else can supply.

Follows invariant #6: returns None on anything it cannot handle, never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# `if not team.owner_id:` / `if team.owner_id is None:` / `if len(team.name) < 3:`
# The attribute is not always adjacent to `if` — it can sit inside a call such
# as len(...) — so match the first attribute access anywhere in the condition.
_ATTR_GUARD = re.compile(
    r"\bif\b[^:]*?\b(?P<obj>[A-Za-z_]\w*)\.(?P<attr>[A-Za-z_]\w*)\b"
)


@dataclass(frozen=True)
class GuardAttr:
    """An attribute a guard reads, and the value that violates it."""

    obj: str
    attr: str
    violating: str  # rendered Python literal


def parse_guard(raw: str | None) -> GuardAttr | None:
    """Extract the object.attribute a guard tests, and a violating value.

    Only single-attribute guards are handled. Compound conditions
    (`if a.x and b.y:`) are ambiguous about which side to violate, so they are
    left alone rather than guessed at.
    """
    if not raw:
        return None
    text = raw.strip()
    if " and " in text or " or " in text:
        return None

    m = _ATTR_GUARD.search(text)
    if m is None:
        return None
    obj, attr = m.group("obj"), m.group("attr")
    if obj in ("self", "cls"):
        return None  # attribute of the instance under test, not a parameter

    return GuardAttr(obj=obj, attr=attr, violating=_violating_value(text))


def _violating_value(text: str) -> str:
    """The literal that makes this guard's condition true.

    `if not x.attr:` and `if x.attr is None:` both fire on None. A length or
    emptiness check fires on an empty string. Comparisons against a number fire
    on 0. None is the safe default: it is falsy, and these guards are
    overwhelmingly null checks.
    """
    if re.search(r"len\(\s*\w+\.\w+\s*\)", text):
        return '""'
    if re.search(r"[<>]=?\s*\d", text):
        return "0"
    return "None"


def build(
    type_name: str | None,
    module: str | None,
    guard: GuardAttr | None,
) -> str | None:
    """Return a MagicMock expression, or None if it would be useless.

    Without a guard attribute the mock is all-truthy and cannot make any guard
    fire, so we decline rather than emit something that wastes two pytest runs
    and lands in the rejected bucket.
    """
    if guard is None:
        return None

    mock = "__import__('unittest.mock', fromlist=['MagicMock']).MagicMock"
    kwargs = []
    if type_name and module:
        kwargs.append(
            f"spec=__import__({module!r}, fromlist=[{type_name!r}]).{type_name}"
        )
    kwargs.append(f"{guard.attr}={guard.violating}")
    expr = f"{mock}({', '.join(kwargs)})"

    try:
        compile(expr, "<guard_mock>", "eval")
    except SyntaxError:
        return None
    return expr
