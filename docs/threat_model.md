# NEXUS Threat Model (Fase 13)

## STRIDE Overview

### Spoofing
- User identity spoofed via unauthenticated calls - mitigated by ownership checks and authenticated context (API endpoints scope by user; no implicit trust in client IDs).
- AgentRun/agent identity forged - IDs are validated/owned; cross-run/cross-agent isolation enforced.
- Tool identity - namespaced (skill.action), registered in ToolRegistry/Catalog; MCP tools mapped to internal names with system metadata.
- MCP server - server identity tracked; tools pass through TrustEngine.
- Webhook spoofed - event ingress should validate authenticity/signature/timestamp/replay when configured.

### Tampering
- Plan tampered - PlanValidator rejects reserved/system args, unknown tools, path escapes; cannot redefine risk/permission.
- Arguments - validated by tool schemas (extra=forbid), reserved names blocked, path/command/network checks.
- Permissions/policies - modified only by application code; external content cannot change.
- Memory - ownership-scoped; not privileged instructions (separated from system policy).
- ScheduledJob - owned by user, state transitions controlled, idempotency.

### Repudiation
- Actions must be auditable - SecurityAuditLog records authorization decisions (event, user/agent/run, tool, decision, policy, risk, reason). Audit best-effort, not modifiable by LLM/ToolExecutor.
- Approvals/decisions - provenance recorded (human_approved flag when applicable).

### Information Disclosure
- Memory leakage - ownership-scoped queries/filters, cross-user searches excluded.
- Cross-user access - owner-scoped repository lookups (404 equivalent on not found/unauthorized).
- Secrets in logs/responses - redaction in runtime events (credential-shaped keys dropped), secret scanning guidance; no secrets to LLM unnecessarily.
- Data across AgentRuns/users - isolation enforced via IDs/ownership.

### Denial of Service
- Agent/tool loops - max_iterations, max_tool_calls, max_denied_actions, max_permission_requests, max_runtime_seconds, per-session budgets.
- Prompt/request flooding - rate limiting, body size limits.
- Scheduler/MCP/event flooding - rate limits, concurrency limits per user.

### Elevation of Privilege
- LLM self-authorization - impossible (TrustEngine separate, single gate). LLM cannot set permission/risk/trusted.
- Tool calling another tool bypassing TrustEngine - no direct cross-tool elevation; all calls via executor with TrustEngine.
- Skills/MCP bypassing TrustEngine - enforced by pipeline; RuntimeToolExecutor requires authorization for sandboxed tools.
- Frontend manipulating permissions - backend source of truth.
- ScheduledJob outside scope - runs as job owner, same policy evaluation each time.
- Runtime host access - no host fallback; filesystem/network/process constraints; fail-closed.

## Critical Attack Scenarios & Mitigations

| Attack | Surface | Mitigation |
|---|---|---|
| Prompt injection (ignore instructions) | External content -> LLM | System/instructions separate from untrusted data; TrustEngine decides actions, not LLM; policy blocks dangerous actions regardless of text. |
| Tool impersonation | Plan | Tool names namespaced/registered; outside catalog rejected; PlanValidator checks availability. |
| Permission replay | Authorization | ExecutionAuthorization minted per call, validated at execution; expired rejected; consumed semantics prevent reuse. |
| Permission escalation | Plan change after approval | Gate re-evaluated on resume/execute; approval context tied to (run,tool,args); changes require re-authorization. |
| Memory poisoning | Stored memory | Memory not privileged; separated from system policy; treated as context. |
| Path traversal | File paths | Canonicalization, workspace containment, forbidden fragments blocked by PlanValidator/CommandPolicy. |
| SSRF | HTTP/Web Research | Network default DENY, explicit allowlist required; endpoints validated before use. |
| Oversized payload | Requests | Body size limits, output size limits, resource limits. |
| Agent infinite loop | Looping | Budget limits, deadlines, audit on exhaustion. |
| MCP malicious output | MCP responses | Treated as untrusted data; cannot modify policies; tools still gated by TrustEngine. |
| Webhook replay | Events | Timestamp/signature/idempotency required when implemented. |
| Cross-user access | IDs | Owner-scoped lookups, 404 on mismatch, no enumeration via different responses. |
| Host access | Runtime | No host fallback, sandbox isolation, allowlists, command policy. |
| Secret exfiltration | Logs/prompts/responses | Redaction, avoid logging secrets, secret scanning, no unnecessary LLM exposure. |
| Scheduler abuse | Jobs | Ownership, idempotency keys, claim CAS, paused/cancelled blocked, concurrency limits, payload size limits. |
