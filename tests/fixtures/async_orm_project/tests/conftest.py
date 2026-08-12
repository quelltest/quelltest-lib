import pytest
import pytest_asyncio

from app.models import AsyncSession, Team


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Async session fixture — exactly what quelltest must reuse."""
    session = AsyncSession()
    yield session


@pytest.fixture
def team() -> Team:
    return Team(id=1, owner_id=42, plan="pro")
