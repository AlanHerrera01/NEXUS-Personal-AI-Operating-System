from sqlalchemy.orm import Session

from app.domain.entities.runtime_settings import RuntimeSettings
from app.domain.repositories.runtime_settings_repository import (
    RuntimeSettingsRepository,
)
from app.infrastructure.persistence.models.runtime_settings_model import (
    RuntimeSettingsModel,
)

#: The primary key of the one settings row. A constant rather than a generated
#: id, because "the settings" are singular and a second row would be a bug, not
#: a second configuration.
SETTINGS_ROW_ID = "global"


class SqlAlchemyRuntimeSettingsRepository(RuntimeSettingsRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> RuntimeSettings | None:
        model = self.session.get(RuntimeSettingsModel, SETTINGS_ROW_ID)
        if model is None:
            return None
        return RuntimeSettings(
            model=model.model,
            temperature=model.temperature,
            max_tokens=model.max_tokens,
            request_timeout_seconds=model.request_timeout_seconds,
            notifications_enabled=model.notifications_enabled,
            updated_at=model.updated_at,
        )

    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        model = self.session.get(RuntimeSettingsModel, SETTINGS_ROW_ID)
        if model is None:
            model = RuntimeSettingsModel(id=SETTINGS_ROW_ID)
            self.session.add(model)
        # Every column is written, including the ``None``s: clearing an override
        # is a real change and has to reach the database as NULL.
        model.model = settings.model
        model.temperature = settings.temperature
        model.max_tokens = settings.max_tokens
        model.request_timeout_seconds = settings.request_timeout_seconds
        model.notifications_enabled = settings.notifications_enabled
        self.session.commit()
        return RuntimeSettings(
            model=model.model,
            temperature=model.temperature,
            max_tokens=model.max_tokens,
            request_timeout_seconds=model.request_timeout_seconds,
            notifications_enabled=model.notifications_enabled,
            updated_at=model.updated_at,
        )
