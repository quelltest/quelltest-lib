"""Async service guards — the shape that produced 0-for-0 in the QA pass."""
from __future__ import annotations

from app.models import AsyncSession, Team

MAX_FREE_MEMBERS = 5


async def add_member(db: AsyncSession, team: Team, user_id: int) -> dict:
    """Add a member to a team.

    Raises:
        ValueError: if user_id is not positive or the team has no owner.
    """
    if user_id <= 0:
        raise ValueError("user_id must be positive")
    if not team.owner_id:
        raise ValueError("team has no owner")
    if team.plan == "free" and len(team.members) >= MAX_FREE_MEMBERS:
        raise ValueError("free plan member limit reached")
    team.members.append(user_id)
    await db.commit()
    return {"team_id": team.id, "user_id": user_id}


async def rename_team(db: AsyncSession, team: Team, name: str) -> dict:
    """Rename a team.

    Raises:
        ValueError: if name is empty or too short.
    """
    if not name:
        raise ValueError("name is required")
    if len(name) < 3:
        raise ValueError("name must be at least 3 characters")
    await db.commit()
    return {"team_id": team.id, "name": name}
