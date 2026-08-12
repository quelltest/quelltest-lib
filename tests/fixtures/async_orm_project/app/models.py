"""ORM-shaped domain objects, mirroring the codebase spec10 §0 describes."""
from __future__ import annotations


class Team:
    def __init__(self, id: int, owner_id: int | None, plan: str = "free"):
        self.id = id
        self.owner_id = owner_id
        self.plan = plan
        self.members: list[int] = []


class AsyncSession:
    """Stand-in for sqlalchemy.ext.asyncio.AsyncSession."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True
