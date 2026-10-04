"""Keep cached process settings from leaking between tests."""

import pytest

from echora_analysis.settings import get_settings


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_compute_choice: use the database-backed compute choice"
    )


@pytest.fixture(autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def local_compute_by_default(monkeypatch, request):
    """Jobs without a recorded location ask the database for the instance default.
    Unit tests have no database, so they compute locally unless a test opts out."""
    if "real_compute_choice" in request.keywords:
        yield
        return
    from echora_analysis import external_processing

    monkeypatch.setattr(
        external_processing, "compute_for", lambda user_id, requested: requested or "local"
    )
    yield
