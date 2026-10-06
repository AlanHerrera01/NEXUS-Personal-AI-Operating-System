from app.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings", "settings_dependency"]


def settings_dependency() -> Settings:
    return get_settings()
