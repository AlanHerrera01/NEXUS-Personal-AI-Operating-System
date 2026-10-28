from datetime import datetime

from app.domain.ports.tool import ToolOutput

SKILL_NAME = "docker"


class DockerLogsOutput(ToolOutput):
    container: str
    content: str
    truncated: bool = False
    fetched_at: datetime
