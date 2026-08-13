"""One pre-existing test, so coverage attribution has something real to find.

Keep this file to the single hand-written test below. `quell find --fix`
appends generated tests here; if those are committed, the G4 gate reports
"0 untested / 5 total" and silently stops measuring anything. That happened
once already -- see the commit that added this docstring.
"""
import pytest

from app.teams import add_member


async def test_happy_path_adds_a_member(db_session, team):
    result = await add_member(db=db_session, team=team, user_id=7)
    assert result["user_id"] == 7
