from app.domain.ports.skill import SkillDefinition
from app.domain.ports.skill_selector import SkillSelector


class KeywordSkillSelector(SkillSelector):
    """Deterministic selector: matches skill names/keywords, otherwise falls back."""

    def __init__(self, fallback_to_all: bool = True) -> None:
        self.fallback_to_all = fallback_to_all

    def select(self, request: str, available: list[SkillDefinition]) -> list[SkillDefinition]:
        enabled = [definition for definition in available if definition.enabled]
        matched = [definition for definition in enabled if definition.matches(request)]
        if matched:
            return matched
        return enabled if self.fallback_to_all else []


class AllEnabledSkillSelector(SkillSelector):
    """Exposes every enabled skill; useful for small agents and for debugging."""

    def select(self, request: str, available: list[SkillDefinition]) -> list[SkillDefinition]:
        return [definition for definition in available if definition.enabled]
