from abc import ABC, abstractmethod

from app.domain.entities.runtime_settings import RuntimeSettings


class RuntimeSettingsRepository(ABC):
    """Storage for the single row of runtime overrides.

    A deployment has one effective model and one set of generation parameters,
    so this is deliberately a singleton read and write rather than a collection.
    """

    @abstractmethod
    def get(self) -> RuntimeSettings | None:
        """The stored overrides, or ``None`` when nothing has been saved yet."""
        raise NotImplementedError

    @abstractmethod
    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        """Persist the whole override row and return what was stored."""
        raise NotImplementedError
