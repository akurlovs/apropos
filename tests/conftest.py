import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))
# Tests run against a frozen copy of the data, so data/ can grow without changing any expected figure.
os.environ["DATA_DIR"] = str(FIXTURES)


@pytest.fixture
def data_copy(tmp_path):
    """A private, editable copy of the frozen data."""
    d = tmp_path / "data"
    shutil.copytree(FIXTURES, d)
    return d


@pytest.fixture
def load_data():
    """Load a scenario's data for one test, then return to the frozen data."""
    from backend import db

    def _load(path):
        db.load(path)

    yield _load
    db.load(FIXTURES)
