from sqlalchemy.orm import Session

from app.domain.entities.skill import Skill
from app.domain.repositories.skill_repository import SkillRepository
from app.infrastructure.persistence.mappers.domain_mappers import skill_from_model, skill_to_model
from app.infrastructure.persistence.models import SkillModel


class SqlAlchemySkillRepository(SkillRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, skill: Skill) -> Skill:
        existing = self.session.get(SkillModel, skill.name)
        if existing is None:
            self.session.add(skill_to_model(skill))
        else:
            existing.description = skill.description
            existing.risk_level = skill.risk_level.value
            existing.enabled = skill.enabled
        self.session.commit()
        return skill_from_model(self.session.get(SkillModel, skill.name))

    def get_by_name(self, name: str) -> Skill | None:
        model = self.session.get(SkillModel, name)
        return skill_from_model(model) if model else None
