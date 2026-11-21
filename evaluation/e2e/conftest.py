"""Pytest configuration and shared fixtures for evaluation/e2e/."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from helpers import MockScholarlyServer, PdfFactory, REPO_ROOT, WorkspaceFactory


def pytest_addoption(parser: pytest.Parser) -> None:
    try:
        parser.addoption(
            "--live",
            action="store_true",
            default=False,
            help="Execute @pytest.mark.live external network audits.",
        )
    except ValueError:
        # Option already registered by an ancestor conftest.py.
        pass


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: marks tests that require live external network/API access (skipped unless --live or RUN_LIVE_AUDITS=1).",
    )


def _live_enabled(config: pytest.Config) -> bool:
    if os.environ.get("RUN_LIVE_AUDITS") == "1" or os.environ.get("RESEARCH_SCIENTIST_LIVE") == "1":
        return True
    try:
        return bool(config.getoption("--live"))
    except ValueError:
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _live_enabled(config):
        return
    skip_live = pytest.mark.skip(reason="need --live or RUN_LIVE_AUDITS=1 to run live network audits")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def _session_https_server():
    server = MockScholarlyServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def mock_server(_session_https_server: MockScholarlyServer) -> MockScholarlyServer:
    _session_https_server.reset()
    return _session_https_server


@pytest.fixture()
def pdf_factory() -> PdfFactory:
    return PdfFactory()


@pytest.fixture()
def workspace_factory() -> WorkspaceFactory:
    return WorkspaceFactory()
