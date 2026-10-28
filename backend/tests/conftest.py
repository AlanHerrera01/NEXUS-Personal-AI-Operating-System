"""API behavior tests use an authenticated operator without distributing a key.

Authentication boundary tests create a separate application without this
override, and exercise missing/invalid credentials against real routes.
"""
import pytest


@pytest.fixture(autouse=True)
def authenticated_operator_for_api_behavior():
    from app.main import app
    from app.presentation.dependencies.identity import require_authentication

    previous = app.dependency_overrides.get(require_authentication)
    app.dependency_overrides[require_authentication] = lambda: None
    yield
    if previous is None:
        app.dependency_overrides.pop(require_authentication, None)
    else:
        app.dependency_overrides[require_authentication] = previous
