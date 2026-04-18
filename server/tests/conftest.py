from __future__ import annotations

import pytest

from server.db import Database
from server.users import UserRepo


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def users(db):
    return UserRepo(db)
