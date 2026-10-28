from dataclasses import dataclass

from app.config.settings import Settings
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.skills.docker.tools.contracts import SKILL_NAME
from app.infrastructure.skills.docker.tools.logs import DockerLogsTool

KEYWORDS = (
    "docker",
    "contenedor",
    "contenedores",
    "container",
    "containers",
    "logs",
    "log",
)


@dataclass
class DockerSkill(Skill):
    settings: Settings

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Read allowlisted container logs through the Docker Engine API.",
            version="1.0.0",
            enabled=True,
            category="docker",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        return [DockerLogsTool(self.settings)]
