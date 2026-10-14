"""Backend test package.

Imported before ``conftest.py``, and therefore before anything under ``app``.
That ordering is what the block below relies on: ``app.main`` builds an app at
import time in the default data directory (``backend/data``). Under
pytest-xdist every worker does that at the same moment, and two processes
creating the same fresh SQLite schema race (``table already exists``). Each
worker gets a private data directory instead; a serial run is unchanged.

The worker's inherited value is replaced, never kept: the controller imports
``conftest.py`` -- and with it ``load_dotenv()`` -- before it spawns workers, so
a developer ``.env`` (``.env.example`` sets ``BRAIN_BUDDY_DATA_DIR``) would
otherwise hand every worker the same directory.
"""

import os
import tempfile

_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _xdist_worker:
    os.environ["BRAIN_BUDDY_DATA_DIR"] = tempfile.mkdtemp(
        prefix=f"brain-buddy-pytest-{_xdist_worker}-"
    )
