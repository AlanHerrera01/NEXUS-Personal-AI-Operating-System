from fastapi.testclient import TestClient

from app.application.settings.service import RuntimeSettingsService
from app.config.settings import Settings, get_settings
from app.domain.entities.runtime_settings import RuntimeSettings
from app.main import app
from app.presentation.dependencies.settings import (
    get_effective_settings,
    get_runtime_settings_service,
)


class FakeSettingsRepository:
    """In-memory stand-in for the singleton override row."""

    def __init__(self) -> None:
        self.stored: RuntimeSettings | None = None
        self.fail = False

    def get(self) -> RuntimeSettings | None:
        if self.fail:
            raise RuntimeError("database is down")
        return self.stored

    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        if self.fail:
            raise RuntimeError("database is down")
        self.stored = settings
        return settings


def _settings() -> Settings:
    return Settings(
        nebius_api_key="test-key",
        nebius_base_url="https://example.invalid",
        nebius_model="env/model",
        llm_temperature=0.1,
        llm_max_tokens=256,
        llm_timeout=30.0,
    )


def _service(
    repository: FakeSettingsRepository, settings: Settings
) -> RuntimeSettingsService:
    return RuntimeSettingsService(
        repository,
        defaults={
            "model": settings.nebius_model,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "request_timeout_seconds": settings.llm_timeout,
            "notifications_enabled": False,
        },
    )


def _override(repository: FakeSettingsRepository) -> Settings:
    settings = _settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_runtime_settings_service] = lambda: _service(
        repository, settings
    )
    return settings


def teardown_function() -> None:
    # Remove only the keys this module installs; ``clear()`` would wipe the
    # module-level overrides other test files register at import time.
    app.dependency_overrides.pop(get_settings, None)
    app.dependency_overrides.pop(get_runtime_settings_service, None)


def test_settings_reports_environment_defaults_when_nothing_is_saved() -> None:
    _override(FakeSettingsRepository())

    body = TestClient(app).get("/api/v1/settings").json()

    assert body["model"] == "env/model"
    assert body["temperature"] == 0.1
    assert body["max_tokens"] == 256
    assert body["overridden"] == []
    assert body["storage_available"] is True
    # The security posture is reported, never offered as a control.
    assert body["trust_editable"] is False
    assert body["memory_firewall_enforced"] is True
    assert body["memory_firewall_editable"] is False
    assert body["provider"] == {
        "name": "nebius",
        "api_key_configured": True,
        "base_url_configured": True,
    }


def test_settings_patch_persists_only_the_safe_subset() -> None:
    repository = FakeSettingsRepository()
    _override(repository)
    client = TestClient(app)

    response = client.patch(
        "/api/v1/settings", json={"model": "runtime/model", "temperature": 0.9}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "runtime/model"
    assert body["temperature"] == 0.9
    assert sorted(body["overridden"]) == ["model", "temperature"]
    # A field that was not sent keeps inheriting the environment.
    assert body["max_tokens"] == 256

    # Durable: a fresh read sees the same thing, and only the sent fields were
    # written (the rest are NULL, i.e. "still inherit").
    again = client.get("/api/v1/settings").json()
    assert again["model"] == "runtime/model"
    assert repository.stored is not None
    assert repository.stored.max_tokens is None
    assert repository.stored.request_timeout_seconds is None


def test_settings_patch_null_returns_a_field_to_its_default() -> None:
    repository = FakeSettingsRepository()
    _override(repository)
    client = TestClient(app)

    client.patch("/api/v1/settings", json={"temperature": 1.5})
    cleared = client.patch("/api/v1/settings", json={"temperature": None}).json()

    assert cleared["temperature"] == 0.1
    assert "temperature" not in cleared["overridden"]


def test_settings_patch_rejects_out_of_range_values() -> None:
    _override(FakeSettingsRepository())

    response = TestClient(app).patch("/api/v1/settings", json={"temperature": 9})

    assert response.status_code == 422


def test_settings_read_degrades_when_storage_is_unavailable() -> None:
    repository = FakeSettingsRepository()
    repository.fail = True
    _override(repository)

    body = TestClient(app).get("/api/v1/settings").json()

    assert body["storage_available"] is False
    assert body["model"] == "env/model"
    assert body["overridden"] == []


def test_settings_write_reports_failure_instead_of_pretending() -> None:
    repository = FakeSettingsRepository()
    repository.fail = True
    _override(repository)

    response = TestClient(app).patch("/api/v1/settings", json={"temperature": 0.5})

    assert response.status_code == 503


def test_effective_settings_applies_saved_overrides() -> None:
    repository = FakeSettingsRepository()
    settings = _settings()
    service = _service(repository, settings)
    service.update({"model": "runtime/model", "max_tokens": 1024})

    effective = get_effective_settings(service=service, settings=settings)

    assert effective.nebius_model == "runtime/model"
    assert effective.llm_max_tokens == 1024
    # Credentials are not in the override vocabulary and cannot move.
    assert effective.nebius_api_key == settings.nebius_api_key
    assert effective.nebius_base_url == settings.nebius_base_url


def test_effective_settings_falls_back_when_storage_is_down() -> None:
    repository = FakeSettingsRepository()
    repository.fail = True
    settings = _settings()
    service = _service(repository, settings)

    effective = get_effective_settings(service=service, settings=settings)

    assert effective.nebius_model == settings.nebius_model
