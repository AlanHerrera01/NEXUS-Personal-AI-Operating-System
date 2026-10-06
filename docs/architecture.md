# NEXUS Architecture Contract

Status: Phase 0, approved as the implementation direction.

## Boundary rule

Dependencies point inward. Domain code must not import FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Nebius, MCP, React, or Docker. Frameworks and external services are adapters at the edge.

```text
Presentation (FastAPI / React)
        -> Application (use cases / orchestration)
        -> Domain (entities / value objects / ports)
        <- Infrastructure adapters (database / LLM / skills / MCP)
```

The current Phase 2 API remains a compatibility slice while the package migration happens incrementally. It is not the target architecture.

## Target backend layout

```text
backend/app/
  domain/
    entities/       Agent, AgentRun, Memory, Task, Skill, Permission, AgentAction
    value_objects/  AgentStatus, RiskLevel, ActionStatus
    repositories/   repository interfaces
    ports/          LLMProvider, EmbeddingProvider, ToolExecutor, PermissionService
  application/
    agents/         create, plan, run, finalize use cases
    memory/         retrieval, write, deletion, policy use cases
    tasks/          task use cases
    skills/         skill registry and selection
    permissions/    trust decisions and approval flows
  infrastructure/
    database/       PostgreSQL/pgvector adapters and migrations
    llm/nebius/     Nebius adapter implementing LLMProvider
    embeddings/     local Sentence Transformers adapter
    mcp/             MCP adapter, when it provides real value
  presentation/
    api/            FastAPI routers
    schemas/        transport DTOs only
    dependencies/   composition root dependencies
  config/           external configuration
```

## Agent lifecycle

Every request creates an explicit `AgentRun` with `CREATED`, `CONTEXT_LOADING`, `PLANNING`, `WAITING_PERMISSION`, `EXECUTING`, `OBSERVING`, `COMPLETED`, `FAILED`, `BLOCKED`, or `CANCELLED` status. The orchestrator owns transitions; an LLM may propose a plan or action but cannot transition security state or execute a tool directly.

```text
request -> create run -> load context -> retrieve memory -> plan
        -> validate plan -> select skill -> trust decision
        -> execute -> observe -> finalize -> memory policy -> end run
```

## Ports and dependency injection

Application services receive abstractions through constructors or FastAPI dependency providers:

- `LLMProvider`: generates a compact plan or response.
- `EmbeddingProvider`: creates local memory embeddings; never Nebius.
- `MemoryRepository`, `TaskRepository`, `AgentRepository`: persistence contracts.
- `ToolExecutor`: executes a validated action without exposing its adapter.
- `PermissionService`: returns `ALLOW`, `ASK`, or `DENY` independently of the LLM.
- `ContextProvider`: composes user context, memories, tasks, skills, permissions, and request.

The composition root selects in-memory adapters for early tests and PostgreSQL/Nebius adapters only in later phases.

## Security invariants

1. The LLM produces proposals, never authorization decisions.
2. High-risk operations are denied by policy, not merely by prompt instructions.
3. Medium-risk operations pause in `WAITING_PERMISSION` and require explicit user approval.
4. The memory policy handles explicit `No guardes esto.` as `DO_NOT_SAVE` independently of the LLM.
5. Filesystem adapters expose allowlisted resources only; there is no global filesystem tool.
6. Logs contain action metadata and outcomes, never API keys or sensitive payloads.

## Delivery phases

0. Architecture contract (this document)
1. Skeleton: configuration, logging, DI, health, initial tests (completed)
2. Domain entities, value objects, ports, services, and use cases (completed)
3. PostgreSQL/SQLAlchemy/Alembic repositories (completed)
4. Memory services, policy, firewall, retrieval, and user control (completed)
5. LLMProvider plus isolated Nebius adapter (completed)
6. Agent orchestrator lifecycle, tools, observations, and trust flow (completed)
7. Skills and tool system: SkillRegistry, SkillSelector, TaskSkill, MemorySkill (completed)
8. Trust Engine
9. MCP where justified
10. Hermes/NemoClaw/OpenShell compatibility research and sandbox (completed — see [sandbox.md](sandbox.md))
11. Frontend workflows
12. Scheduler and proactive events
13. Security hardening
14. Docker and deployment
15. Hackathon demo

Each phase must pass its focused tests before the next phase starts.

## Sandboxed execution

Phase 10 adds `AgentRuntimePort` and the `RuntimeToolExecutor` that routes
sandbox-backed tools through it. NEXUS remains the orchestrator; OpenShell is
the isolation runtime; Hermes is an optional payload inside the sandbox;
NemoClaw is not integrated, because adopting a second orchestrator would
duplicate the authority this architecture already has.

The guarantees, the code that enforces each one, and the known gaps are
documented in [docs/sandbox.md](sandbox.md).

Two invariants extend the list above:

7. A Trust Engine `ALLOW` is necessary but not sufficient: a sandbox-backed tool
   also needs an unconsumed `ExecutionAuthorization` bound to that run and tool.
8. No runtime means no execution. There is no host fallback, and a runtime that
   cannot be created or started fails the run rather than degrading.

## Skills and tools

A Skill is a capability; a Tool is one concrete action inside it. Skills own their tools, the
`SkillRegistry` publishes them into the single `ToolRegistry`, and the orchestrator only ever
consults the tool catalog.

```text
AgentOrchestrator -> ToolCatalog -> SkillSelector -> SkillRegistry -> Skill -> Tool
                                                                   -> ToolRegistry -> Tool
```

- `SkillDefinition` and `ToolDefinition` are descriptive only; neither holds execution logic.
- Tool names are namespaced as `skill.action`; identity and routing arguments are reserved.
- Each tool declares an input schema, a typed input/output DTO, a risk level, `read_only` and
  `side_effect`; the TrustEngine remains the authority, the declared risk is only an input.
- Disabling a skill withdraws its tools from the `ToolRegistry`, so the agent never sees them.
- The catalog narrows the offered tools per request (enabled + relevant + granted skills), and the
  orchestrator rejects any tool outside that set.
- Adding a skill is composition only: register it in `build_skills(...)`. No change to the
  orchestrator, brain, planner, trust engine, memory, or LLM provider.

