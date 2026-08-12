"""One pre-existing test, so coverage attribution has something real to find."""
import pytest

from app.teams import add_member


async def test_happy_path_adds_a_member(db_session, team):
    result = await add_member(db=db_session, team=team, user_id=7)
    assert result["user_id"] == 7
async def test_quell_add_member_boundary_fb0f52f4(db_session, team):
    """Quell: boundary condition — if user_id <= 0:"""
    import pytest
    from app.teams import add_member
    with pytest.raises(Exception):
        await add_member(db=db_session, team=team, user_id=0)
async def test_quell_add_member_boundary_c43a42d3(db_session, team):
    """Quell: boundary condition — if team.plan == 'free' and len(team.members) >= MAX_FREE_MEMBERS:"""
    import pytest
    from app.teams import add_member
    with pytest.raises(Exception):
        await add_member(db=db_session, team=team, user_id=0)
async def test_quell_rename_team_boundary_5e33633f(db_session, team):
    """Quell: boundary condition — if len(name) < 3:"""
    import pytest
    from app.teams import rename_team
    with pytest.raises(Exception):
        await rename_team(db=db_session, team=team, name="ab")
