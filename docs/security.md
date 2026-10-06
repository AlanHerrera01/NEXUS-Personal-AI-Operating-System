# NEXUS Security Documentation (Fase 13)

## Security Architecture
The execution path is strictly ordered: User -> Frontend -> API -> Agent Orchestrator -> PlanValidator -> TrustEngine -> ToolExecutor -> (MCP/Native) -> Agent Runtime -> Sandbox. LLM produces reasoning/proposals only; never authorizes or executes.

## Trust Boundaries
Trusted: app code (orchestrator, TrustEngine, PlanValidator, runtime policy), config. Untrusted: user input, LLM output, MCP output, webhooks/web content, uploads, memory content, event payloads. External data is DATA, not AUTHORITY.

## Invariants
1. LLM cannot authorize itself. 2. LLM cannot directly execute tools. 3. Frontend cannot authorize itself. 4. Scheduler cannot bypass TrustEngine/PlanValidator. 5. MCP cannot bypass TrustEngine. 6. Tools cannot bypass TrustEngine. 7. Memory cannot modify security policy. 8. External content cannot modify security policy. 9. Runtime failure cannot trigger host execution (fail-closed). 10. User resources isolated by ownership. 11. High-risk actions need explicit policy ALLOW. 12. Expired permissions cannot be reused. 13. Cancelled/paused jobs cannot execute. 14. Secrets not exposed to LLM unnecessarily; redacted from logs/events. 15. Security failures must fail closed (DENY/default deny).

## Authorization
PlanValidator validates structure; TrustEngine evaluates policy/permissions (default DENY). On ALLOW, ExecutionAuthorization minted (agent_id, agent_run_id, tool_name, user_id, policy_id, TTL) and validated at execution. RuntimeToolExecutor refuses sandboxed tools without valid authorization. Both execute/resume share the single _gate path.

## Isolation
AgentRuntimePort with providers OPENSHELL/LOCAL/IN_MEMORY; unknown provider is startup error. No host fallback. Workspace containment (canonicalized), command/network/filesystem/process/credential/resource limits, per-session budgets, timeouts.

## Memory
Ownership-scoped, separated from system policy, DO_NOT_SAVE respected, no cross-user leakage.

## Always-On/Scheduler
Job owner passed as acting user, same pipeline, idempotency, insert-then-claim, try_advance_schedule CAS, recovery for abandoned executions, paused/cancelled jobs cannot run, concurrency limits.

## MCP
Mapped to internal ToolDefinition (system-controlled metadata, not trusted), passes through TrustEngine/authorization.

## API Security
Owner-scoped lookups, rate limiting, body size limits, explicit CORS origins, security headers, request IDs. No implicit trust in client identity.
