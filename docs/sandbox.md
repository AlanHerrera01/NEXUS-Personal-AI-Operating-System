# Phase 10 — Sandboxed Execution

This document records how NEXUS executes work in an isolated environment, why
OpenShell / Hermes / NemoClaw are used the way they are, and which guarantees
are enforced in code rather than merely described.

## Roles

The three NVIDIA projects are not interchangeable, and using them as though they
were would give NEXUS two orchestrators and two sources of authority.

| Project | Role in NEXUS | Explicitly not |
| --- | --- | --- |
| **OpenShell** | The isolation runtime. Backs `AgentRuntimePort`: creates a sandbox, applies a policy, runs a process, tears it down. | Not an orchestrator, planner or memory store. |
| **NemoClaw** | Evaluated, not integrated. It wraps OpenShell to provide an agent *product*. | Not wired as a CLI. Doing so would duplicate the orchestrator, the memory layer and the permission authority that Phases 1–9 already own. |
| **Hermes** | Optional sandboxed *payload*: a model/agent workload that may run as the job inside an OpenShell sandbox. | Not a second agent with its own memory, permissions or approval flow. |

The rule that follows: **NEXUS stays the orchestrator.** One planner, one memory,
one Trust Engine, one audit trail. OpenShell confines the work those decisions
authorise. Where a tool needs egress credentials, they are injected at the
boundary by `CredentialService`, never handed to the model.

Upstream guidance is consistent with this: NVIDIA's own ecosystem documentation
recommends that an internal platform use OpenShell plus its own orchestration
rather than adopting a bundled agent product alongside one.

References:

- <https://docs.nvidia.com/openshell/sandboxes/manage-sandboxes>
- <https://nvidia-openshell.mintlify.app/reference/cli-sandbox>
- <https://docs.nvidia.com/nemoclaw/user-guide/openclaw/about/ecosystem.md>
- <https://docs.nvidia.com/nemoclaw/user-guide/hermes/get-started/quickstart>

## Port and adapters

```text
Orchestrator -> RuntimeToolExecutor -> AgentRuntimeService -> AgentRuntimePort
                                                                      |
                        +----------------------+----------------------+----+
                        |                      |                      |
              OpenShellRuntimeAdapter   LocalSandboxRuntime   FakeAgentRuntime
                 (OpenShell CLI)        (dev only, no        (tests)
                                       kernel isolation)
```

`AgentRuntimePort` is the only thing the application layer knows. The Domain has
no import of OpenShell, Docker, or any vendor SDK; `RuntimeProvider` is used for
reporting and never switches behaviour.

Adapter selection is explicit configuration. An unrecognised provider is a
startup error, never a silent substitution — falling back would void every
guarantee in this document.

### OpenShell CLI surface used

Verified signatures, each capability-probed at startup because installed builds
and documentation have been observed to disagree:

```text
openshell sandbox create [OPTIONS] [-- COMMAND]...   # no command => retained shell
openshell sandbox exec -n NAME [--timeout s] -- ARGV...
openshell sandbox upload NAME LOCAL_PATH [DEST]
openshell sandbox download NAME SANDBOX_PATH [DEST]
openshell sandbox get NAME [--policy-only]
openshell sandbox stop NAME
openshell sandbox delete NAME
openshell policy set NAME --policy FILE [--wait]
```

The adapter probes per-leaf help and refuses rather than guessing a flag it has
not seen. A gateway port is never hardcoded; it is discovered from the installed
CLI's own configuration.

## Enforcement points

A guarantee is only real if some code fails when it is violated. Each row below
names the code that fails.

| Guarantee | Enforced in | Failure |
| --- | --- | --- |
| No Trust Engine `ALLOW`, no execution | `AgentRuntimeService._pre_execution_checks` | `AUTHORIZATION_DENIED`, `MISSING_AUTHORIZATION` event |
| An authorization cannot be replayed | `ExecutionAuthorization.consume()` before dispatch | `AUTHORIZATION_DENIED` |
| A run cannot drive another run's sandbox | `RuntimeSession.assert_execution_target` | `CROSS_SESSION_DENIED`, `CROSS_SESSION_ACCESS_DENIED` event |
| Paths stay inside the workspace | `path_guard.canonicalise` + `RuntimePolicy.allows_path` | `FILESYSTEM_DENIED` |
| No traversal via a shared path prefix | canonicalisation before containment, segment-aware | `FILESYSTEM_DENIED` |
| Writes cannot escape (`sort -o /etc/x`) | `CommandPolicy` write-flag parsing (`-o`, `-of`, `--output`, `--output=`) | `COMMAND_DENIED` |
| Only allowlisted binaries run | `RuntimePolicy.allows_binary` | `PROCESS_DENIED` |
| Egress stays off by default | `NetworkPolicy` (`DENY` default, `ALLOW` never constructible) | `NETWORK_DENIED`, `BLOCKED_NETWORK_REQUEST` event |
| Declared destinations are checked | `AgentRuntimeService._check_network` before the process starts | `NETWORK_DENIED` |
| Secrets never enter the sandbox | `CredentialPolicy.exposes_secrets_to_runtime` in `is_isolation_intact` | session never starts |
| Credential-shaped variables are refused | `AgentRuntimeService._check_credentials` | `CREDENTIAL_DENIED` (name recorded, never value) |
| Per-session tool-call budget | `RuntimeSession.record_execution` / `has_execution_budget` | `RESOURCE_LIMIT_EXCEEDED` |
| Workload timeout | `min(request, policy)` in `AgentRuntimeService.execute` | `RUNTIME_TIMEOUT` event |
| Expired sessions do not execute | `RuntimeSession.is_expired` | `RUNTIME_EXPIRED`, `EXPIRED_RUNTIME_EXECUTION` event |
| A runtime failure never runs on the host | no host fallback exists; `RuntimeUnavailableError` surfaces | run → `FAILED` |
| A runtime failure cannot strand a run | handler in `AgentOrchestrator.execute` | run → `FAILED`, not left `EXECUTING` |

## Invariants worth stating explicitly

**No host fallback.** There is no code path that runs a workload outside the
sandbox when the sandbox is unavailable. `RuntimeUnavailableError` propagates
and the run fails. A fallback would be indistinguishable from success.

**`DENY` is the default and `ALLOW` cannot be constructed.** `NetworkPolicy`
raises `PolicyViolation` on `mode="ALLOW"`. Posture is allowlist-only.

**Modes arriving as strings are coerced.** A `NetworkPolicy` built from a
database row or env var gets `mode` as a plain `str`. Every check compares by
identity (`is not NetworkMode.ALLOW`), and `"ALLOW" == NetworkMode.ALLOW` while
`"ALLOW" is not NetworkMode.ALLOW`. Uncoerced, a mode read as `RESTRICTED` would
pass an `is_restricted` check and open egress. `__post_init__` coerces before
validating for exactly this reason.

**Paths are canonicalised before containment.** `<workspace>/../../etc` has the
workspace as a string prefix but is not inside it. Both sides of the comparison
are normalised, and a workspace configured with Windows separators still matches
a request using forward slashes.

**A timeout is distinguishable.** `RUNTIME_TIMEOUT` was an enum member that no
code path could emit, so a run killed at the limit was indistinguishable from any
other failure.

## Security events

`RuntimeEventRecorder` emits structured records carrying ownership coordinates
(user, agent, run, runtime, tool). Every payload is passed through `redact()`,
which drops credential-shaped keys. A security record may name a *credential* or a
*blocked host*; it never carries a value.

`UNAUTHORIZED_FILESYSTEM_ACCESS`, `BLOCKED_NETWORK_REQUEST`, `FORBIDDEN_PROCESS`,
`CREDENTIAL_ACCESS_DENIED`, `POLICY_VIOLATION`, `SANDBOX_ESCAPE_ATTEMPT`,
`CROSS_SESSION_ACCESS_DENIED`, `MISSING_AUTHORIZATION`,
`EXPIRED_RUNTIME_EXECUTION`, `RESOURCE_LIMIT_EXCEEDED`.

## Transfer safety

`upload` refuses a source that is not a regular file, so a directory or symlink
is not handed to the CLI. `download` requires an absolute destination, writes to
a `.partial` sibling and moves it into place only on success, so a failed
transfer never leaves a truncated file under the real name, and treats a
reported success that produced no file as a failure rather than an `OSError`.

In the local adapter, relative sandbox paths are anchored to the workspace.
Resolving them against the process would refuse every legitimate relative path
*and* anchor the sandbox view to the API server's working directory.

## Configuration

```text
runtime_enabled=false                 # master switch; off by default
runtime_provider=LOCAL                # OPENSHELL | LOCAL | IN_MEMORY
runtime_workspace_root=./.nexus-runtime
runtime_max_execution_seconds=30      # the workload
runtime_command_timeout_seconds=120   # the driver; must exceed the above
runtime_max_output_bytes=262144
runtime_max_memory_mb=512
runtime_max_network_requests=16
runtime_max_tool_calls=10
runtime_expiration_seconds=900
runtime_allowed_binaries=/usr/bin/ls,/usr/bin/cat,/usr/bin/wc,/usr/bin/sort
runtime_allowed_endpoints=            # host:port:access triples
runtime_allowed_commands_json=        # full override of the command allowlist
runtime_credential_provider=deny_all  # deny_all | environment | resolver_placeholder
```

`runtime_command_timeout_seconds` is validated at startup to exceed
`runtime_max_execution_seconds`. The driver has to outlive the workload it
carries: collapsing the two would kill the driver mid-negotiation and report it
as a workload timeout.

## Known gaps

- **No authentication layer.** NEXUS has no authentication, so `/api/v1/runtime`
  identifies nobody and is not an access-control boundary. The runtime responses
  deliberately omit host filesystem paths. This must be closed before any public
  exposure.
- **Local provider has no kernel isolation.** `LOCAL` confines work to the run
  workspace and validates argv; it is a development runtime, and it says so in
  its own health output.
- **Symlink transfer tests skip on Windows**, where creating a symlink needs
  elevated privileges. They run on Linux CI.