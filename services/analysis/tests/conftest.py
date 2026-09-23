"""Keep cached process settings from leaking between tests."""
import pytest

from echora_analysis.settings import get_settings


@pytest.fixture(autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
