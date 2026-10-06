from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.runtime_session import RuntimeSession
from app.domain.repositories.runtime_session_repository import RuntimeSessionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.runtime_policy import (
    CredentialPolicy,
    FilesystemPolicy,
    NetworkEndpoint,
    NetworkPolicy,
    ProcessPolicy,
    ResourceLimits,
    RuntimePolicy,
)
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.domain.value_objects.runtime_state import RuntimeState
from app.infrastructure.persistence.models.runtime_session_model import RuntimeSessionModel

import json


class SqlAlchemyRuntimeSessionRepository(RuntimeSessionRepository):
    """Persists runtime sessions. The ``agent_run_id`` index enforces per-run scoping."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, session: RuntimeSession) -> RuntimeSession:
        model = RuntimeSessionModel(
            id=str(session.id),
            user_id=str(session.user_id) if session.user_id else None,
            agent_id=str(session.agent_id),
            agent_run_id=str(session.agent_run_id),
            provider=session.provider.value,
            sandbox_id=session.sandbox_id,
            state=session.state.value,
            workspace_path=session.workspace_path,
            policy=self._policy_to_json(session.policy),
            metadata_json=json.dumps(session.metadata, default=str),
            created_at=session.created_at,
            updated_at=session.updated_at,
            expires_at=session.expires_at,
            started_at=session.started_at,
            stopped_at=session.stopped_at,
            last_error=session.last_error,
        )
        self.session.merge(model)
        self.session.commit()
        return session

    def get_by_id(self, session_id: EntityId) -> RuntimeSession | None:
        stmt = select(RuntimeSessionModel).where(RuntimeSessionModel.id == str(session_id))
        result = self.session.execute(stmt).scalar_one_or_none()
        return self._to_entity(result) if result else None

    def get_by_run_id(self, agent_run_id: EntityId) -> list[RuntimeSession]:
        stmt = (
            select(RuntimeSessionModel)
            .where(RuntimeSessionModel.agent_run_id == str(agent_run_id))
            .order_by(RuntimeSessionModel.created_at)
        )
        return [self._to_entity(row) for row in self.session.execute(stmt).scalars().all()]

    def list_by_state(self, state: RuntimeState) -> list[RuntimeSession]:
        stmt = (
            select(RuntimeSessionModel)
            .where(RuntimeSessionModel.state == state.value)
            .order_by(RuntimeSessionModel.created_at)
        )
        return [self._to_entity(row) for row in self.session.execute(stmt).scalars().all()]

    def delete(self, session_id: EntityId) -> None:
        stmt = select(RuntimeSessionModel).where(RuntimeSessionModel.id == str(session_id))
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is not None:
            self.session.delete(result)
            self.session.commit()

    # -- mapping -----------------------------------------------------------

    def _policy_to_json(self, policy: RuntimePolicy) -> str:
        return json.dumps(
            {
                "filesystem": {
                    "workspace_only": policy.filesystem.workspace_only,
                    "workspace_path": policy.filesystem.workspace_path,
                    "read_only_paths": list(policy.filesystem.read_only_paths),
                    "read_write_paths": list(policy.filesystem.read_write_paths),
                },
                "network": {
                    "mode": policy.network.mode.value,
                    "allowed_endpoints": [
                        {
                            "host": e.host,
                            "port": e.port,
                            "protocol": e.protocol,
                            "access": e.access,
                            "path": e.path,
                        }
                        for e in policy.network.allowed_endpoints
                    ],
                    "allowed_binaries": list(policy.network.allowed_binaries),
                },
                "processes": {
                    "max_processes": policy.processes.max_processes,
                    "run_as_user": policy.processes.run_as_user,
                    "run_as_group": policy.processes.run_as_group,
                    "no_new_privileges": policy.processes.no_new_privileges,
                    "allowed_binaries": list(policy.processes.allowed_binaries),
                },
                "resources": {
                    "max_execution_seconds": policy.resources.max_execution_seconds,
                    "max_output_bytes": policy.resources.max_output_bytes,
                    "max_memory_mb": policy.resources.max_memory_mb,
                    "max_cpu": policy.resources.max_cpu,
                    "max_filesystem_bytes": policy.resources.max_filesystem_bytes,
                    "max_network_requests": policy.resources.max_network_requests,
                    "max_tool_calls": policy.resources.max_tool_calls,
                },
                "credentials": {
                    "allow_host_access": policy.credentials.allow_host_access,
                    "allow_runtime_injection": policy.credentials.allow_runtime_injection,
                    "allowed_credential_names": sorted(policy.credentials.allowed_credential_names),
                },
                "expiration_seconds": policy.expiration_seconds,
                "allowed_tool_names": sorted(policy.allowed_tool_names),
            }
        )

    def _to_entity(self, model: RuntimeSessionModel) -> RuntimeSession:
        payload = json.loads(model.policy) if model.policy else {}
        filesystem = payload.get("filesystem", {})
        network = payload.get("network", {})
        processes = payload.get("processes", {})
        resources = payload.get("resources", {})
        credentials = payload.get("credentials", {})

        return RuntimeSession(
            id=EntityId.from_string(model.id),
            user_id=EntityId.from_string(model.user_id) if model.user_id else None,
            agent_id=EntityId.from_string(model.agent_id),
            agent_run_id=EntityId.from_string(model.agent_run_id),
            provider=RuntimeProvider(model.provider),
            sandbox_id=model.sandbox_id,
            state=RuntimeState(model.state),
            workspace_path=model.workspace_path,
            policy=RuntimePolicy(
                filesystem=FilesystemPolicy(
                    workspace_only=filesystem.get("workspace_only", True),
                    workspace_path=filesystem.get("workspace_path", ""),
                    read_only_paths=tuple(filesystem.get("read_only_paths", ())),
                    read_write_paths=tuple(filesystem.get("read_write_paths", ())),
                ),
                network=NetworkPolicy(
                    mode=network.get("mode", "DENY"),
                    allowed_endpoints=tuple(
                        NetworkEndpoint(
                            host=item["host"],
                            port=item["port"],
                            protocol=item.get("protocol", "rest"),
                            access=item.get("access", "read-only"),
                            path=item.get("path"),
                        )
                        for item in network.get("allowed_endpoints", ())
                    ),
                    allowed_binaries=tuple(network.get("allowed_binaries", ())),
                ),
                processes=ProcessPolicy(
                    max_processes=processes.get("max_processes", 64),
                    run_as_user=processes.get("run_as_user", "sandbox"),
                    run_as_group=processes.get("run_as_group", "sandbox"),
                    no_new_privileges=processes.get("no_new_privileges", True),
                    allowed_binaries=tuple(processes.get("allowed_binaries", ())),
                ),
                resources=ResourceLimits(**{
                    key: value for key, value in resources.items() if key in ResourceLimits.__annotations__
                })
                if resources
                else ResourceLimits(),
                credentials=CredentialPolicy(
                    allow_host_access=credentials.get("allow_host_access", False),
                    allow_runtime_injection=credentials.get("allow_runtime_injection", False),
                    allowed_credential_names=frozenset(credentials.get("allowed_credential_names", ())),
                ),
                expiration_seconds=payload.get("expiration_seconds", 900),
                allowed_tool_names=frozenset(payload.get("allowed_tool_names", ())),
            ),
            created_at=model.created_at,
            updated_at=model.updated_at,
            expires_at=model.expires_at,
            started_at=model.started_at,
            stopped_at=model.stopped_at,
            last_error=model.last_error,
            metadata=json.loads(model.metadata_json) if model.metadata_json else {},
        )
