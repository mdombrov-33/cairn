"""Test-wide configuration required during test-module collection."""

import os

# ``cairn.main`` creates its ASGI app at import time, before integration fixtures
# can provide their container URL. The app does not connect until its lifespan.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://cairn:cairn@localhost:5433/cairn")
