import ocd_app.api_client as api_client
import pytest


@pytest.fixture(autouse=True)
def reset_client():
    """Each test starts with a clean base URL + no auth token."""
    api_client.configure(base_url="http://test", token=None)
    yield
    api_client.configure(base_url="http://test", token=None)
