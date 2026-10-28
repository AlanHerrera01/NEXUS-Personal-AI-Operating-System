from dataclasses import dataclass

from app.config.settings import Settings
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.skills.web.tools.contracts import SKILL_NAME
from app.infrastructure.skills.web.tools.fetch import WebFetchTool
from app.infrastructure.skills.web.tools.search import WebSearchTool

KEYWORDS = (
    "web",
    "internet",
    # Phrases instead of the bare verb "buscar": a request such as "buscar
    # recuerdos" would otherwise select this skill and, because the selector
    # returns matches rather than all skills, leave the memory skill out.
    "buscar en internet",
    "búsqueda en internet",
    "busqueda en internet",
    "search",
    "investigar",
    "investigación",
    "investigacion",
    "noticia",
    "noticias",
    "página web",
    "pagina web",
    "documentación",
    "documentacion",
    "url",
    "fetch",
)


@dataclass
class WebSkill(Skill):
    """Public web search and page reading.

    Both tools are read-only. The side effects worth worrying about here are not
    writes on the user's behalf but what a fetched page can talk the model into
    proposing, which is why the fetch excerpt is fenced as untrusted data and
    every hop is checked by the SSRF guard.
    """

    settings: Settings

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Search the public web and read pages as untrusted data.",
            version="1.0.0",
            enabled=True,
            category="knowledge",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        return [
            WebSearchTool(self.settings),
            WebFetchTool(self.settings),
        ]
