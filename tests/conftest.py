from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_services import FakeServices  # noqa: E402
from starbuck.sources import Sources  # noqa: E402


@pytest.fixture
def fake() -> FakeServices:
    return FakeServices()


@pytest.fixture
async def src(fake: FakeServices):
    s = Sources(email="test@example.org", transport=fake.transport(), pacing=False, retry_delay=0)
    yield s
    await s.aclose()
