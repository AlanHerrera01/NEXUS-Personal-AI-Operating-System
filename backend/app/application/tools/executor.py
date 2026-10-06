import asyncio
import logging

from app.domain.ports.tool import ToolContext, ToolObservation
from app.domain.ports.tool_executor import ToolExecutor
from app.domain.ports.tool_registry import ToolRegistry
from app.domain.value_objects.tool_error_code import ToolErrorCode

logger = logging.getLogger(__name__)


class RegistryToolExecutor(ToolExecutor):
    """Runs one registered tool and converts every failure into a ToolObservation."""

    def __init__(self, registry: ToolRegistry, timeout_seconds: float = 30.0) -> None:
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    async def execute(self, tool_name: str, arguments: dict, context: ToolContext) -> ToolObservation:
        tool = self.registry.get(tool_name)
        if tool is None:
            return ToolObservation(tool_name, False, error=str(ToolErrorCode.TOOL_NOT_FOUND))
        try:
            result = await asyncio.wait_for(tool.execute(arguments, context), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("tool %s timed out", tool_name)
            return ToolObservation(tool_name, False, error=str(ToolErrorCode.TOOL_TIMEOUT))
        except Exception:
            logger.exception("tool %s raised an unexpected error", tool_name)
            return ToolObservation(
                tool_name,
                False,
                error=str(ToolErrorCode.TOOL_EXECUTION_FAILED),
                metadata={"correlation_id": context.correlation_id},
            )
        metadata = dict(result.metadata)
        if result.success:
            return ToolObservation(tool_name, True, result.data, metadata=metadata)
        metadata["code"] = result.error_code or str(ToolErrorCode.TOOL_EXECUTION_FAILED)
        error = str(metadata["code"])
        if result.error_message:
            error = f"{error}: {result.error_message}"
        return ToolObservation(tool_name, False, result.data, error=error, metadata=metadata)
