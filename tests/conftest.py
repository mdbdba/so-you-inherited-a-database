"""Shared pytest fixtures.

Key concern: pydantic-settings reads `.env` from the current working directory.
The repo root has a `.env` file with real credentials, which leaks into tests
that use monkeypatch to remove env vars. Running each test in a fresh tmp_path
ensures no .env file is found unless the test explicitly creates one.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_from_env_file(tmp_path, monkeypatch):
    """Change cwd to a temp dir for every test so pydantic-settings cannot
    find the repo-root .env file."""
    monkeypatch.chdir(tmp_path)
