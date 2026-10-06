from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NEXUS API"
    environment: str = "development"
    log_level: str = "INFO"
    # No default password in source. The URL still has to be a *parseable* URL,
    # because the engine is built at import time and an empty string makes every
    # module that imports a repository fail to import -- turning "you forgot to
    # configure the database" into "the whole application will not start", which
    # hides the real problem. So the default names the expected local server and
    # no credential: it parses, then fails to connect, which is the honest and
    # much more legible outcome. A deployment supplies DATABASE_URL explicitly
    # (see .env.example) if the server is elsewhere or needs a password.
    database_url: str = "postgresql+psycopg://nexus@localhost:5432/nexus"
    nebius_api_key: str | None = None
    nebius_base_url: str | None = None
    nebius_model: str | None = None
    llm_timeout: float = 60.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.2
    llm_max_tokens: int = 512
    
    # Security configuration
    trust_default_decision: str = "DENY"
    agent_max_tool_calls: int = 10
    agent_max_permission_requests: int = 3
    agent_max_denied_actions: int = 5
    permission_request_ttl_seconds: int = 300
    disabled_skills: str = ""  # Comma-separated list of disabled skill names

    # -- sandboxed execution (Phase 10) -------------------------------------
    # runtime_provider selects the AgentRuntimePort implementation:
    # OPENSHELL (real isolation), LOCAL (development workspace jail), IN_MEMORY
    # (tests). There is no implicit default that silently picks one for you
    # beyond the deny-by-default LOCAL value below.
    runtime_provider: str = "LOCAL"
    runtime_workspace_root: str = "./.nexus-runtime"
    runtime_max_execution_seconds: float = 30.0
    runtime_max_output_bytes: int = 262_144
    runtime_max_memory_mb: int = 512
    runtime_max_cpu: str = "1"
    runtime_max_filesystem_bytes: int = 67_108_864
    runtime_max_network_requests: int = 16
    runtime_max_tool_calls: int = 10
    runtime_max_processes: int = 64
    runtime_expiration_seconds: int = 900
    # Comma-separated paths the sandbox may read but never write.
    runtime_read_only_paths: str = "/usr,/lib,/lib64,/bin,/sbin,/etc,/dev/urandom"
    # "host:port:access" triples, e.g. "api.example.com:443:read-only".
    runtime_allowed_endpoints: str = ""
    runtime_allowed_binaries: str = "/usr/bin/ls,/usr/bin/cat,/usr/bin/wc,/usr/bin/sort"
    # Overrides the built-in command allowlist entirely when set.
    # JSON object: {"ls": ["-la"], "cat": []}
    runtime_allowed_commands_json: str = ""
    runtime_command_timeout_seconds: float = 120.0
    # Master switch. When false, no sandbox-backed tool is wired at all and the
    # orchestrator keeps using the in-process executor. Enabling it does not by
    # itself allow anything: every call still needs a Trust Engine ALLOW.
    runtime_enabled: bool = False
    # Credential custody. "deny_all" is the default and the only safe one to ship:
    # the other values exist so a deployment opts in deliberately rather than
    # discovering that its process environment is readable by tools.
    #   deny_all             - no credential is resolvable at all
    #   environment           - resolve NEXUS_CRED_* variables under an explicit grant
    #   resolver_placeholder  - hand the sandbox openshell:resolve:env:NAME instead
    runtime_credential_provider: str = "deny_all"
    runtime_credential_names: str = ""

    # -- Always-On (Phase 12) --------------------------------------------
    # Master switch, deny-by-default like runtime_enabled. When false the
    # scheduler loop never starts and the event ingress refuses traffic, so a
    # deployment opts in deliberately instead of discovering that its server
    # wakes itself up.
    always_on_enabled: bool = False
    # How often the polling scheduler looks for due jobs. This is an upper bound
    # on firing lateness, not a guarantee of precision; jobs are clocked to the
    # minute, so polling faster than a few seconds buys nothing.
    always_on_poll_interval_seconds: float = 5.0
    # Ceiling on active jobs a single user may hold. Bounds how much agent work
    # one account can queue if it is forgotten.
    always_on_max_active_jobs_per_user: int = 20
    # Ceiling on a single user's executions in RUNNING at once. This is what
    # stops one user monopolising the worker pool.
    always_on_max_concurrent_runs: int = 3
    # Retries for transient dispatch failures. Kept small on purpose: every
    # retry is a real agent run, and the idempotency key is already spent.
    always_on_max_retries: int = 2
    # Wall-clock budget for one execution. Checked by the dispatcher's caller,
    # not by cancelling a run mid-tool-execution.
    always_on_job_timeout_seconds: int = 300
    # Floor on INTERVAL jobs. A 1-second interval is a denial-of-service button
    # that spends model calls and opens runs forever, so it is refused at
    # creation rather than rate-limited later.
    always_on_min_interval_seconds: int = 300
    always_on_max_events_per_minute: int = 60
    always_on_max_jobs_per_event: int = 20
    # How many due jobs one tick will consider.
    always_on_max_jobs_per_tick: int = 50
    # An occurrence older than this is recorded SKIPPED and rescheduled from now
    # instead of replayed. This is the catch-up policy; replaying a week of
    # missed 5-minute intervals would be a stampede.
    always_on_grace_seconds: int = 900
    # How long an execution may sit RUNNING before recovery assumes its worker
    # died. Must comfortably exceed the job timeout or a slow-but-healthy run
    # gets failed out from under itself.
    always_on_stale_execution_seconds: int = 1_800
    # Shared secret for the external event ingress. When unset, the ingress
    # endpoint refuses every request rather than defaulting to something guessable.
    always_on_event_ingress_secret: str | None = None
    always_on_max_proactive_rules_per_user: int = 50

    # -- security hardening (Phase 13) -------------------------------------
    # Every bound below is declared exactly once, here. Components receive them
    # by injection and keep no private copy, so tightening a limit is a one-line
    # change rather than a hunt through modules that each remembered their own.

    # Agent loop. ``agent_max_tool_calls`` already existed above and is the
    # per-run tool budget; these are the ceiling on reasoning turns and on how
    # long one run may occupy a request.
    agent_max_iterations: int = 10
    agent_max_runtime_seconds: int = 300
    # The orchestrator tracks per-run budgets in memory. Unbounded, that is a
    # slow leak reachable by anyone who can start runs; this caps the table.
    orchestrator_max_tracked_runs: int = 10_000
    # Rejected before a request ever reaches the model. Bounds prompt flooding
    # from the cheapest end, where it is cheapest to refuse.
    agent_max_request_chars: int = 8_000

    # Prompt-injection defence. Detection never rewrites content and never
    # grants or denies authority: it raises an audit event and fences external
    # text so the model can read it as data. The application, not the model and
    # not the detector, still decides what runs.
    injection_detection_enabled: bool = True
    untrusted_data_max_chars: int = 20_000

    # Memory. Content bounds mirror the schema so an oversized write is refused
    # by the same number whether it arrives over HTTP or through a tool.
    memory_max_content_chars: int = 10_000
    memory_secret_block_enabled: bool = True
    # Memory is context, never policy. Storing an instruction aimed at the
    # system is the memory-poisoning vector, so the shape of an injection is
    # recorded at write time even though persistence is still allowed.
    memory_injection_flag_enabled: bool = True

    # HTTP hardening.
    cors_allowed_origins: str = "http://localhost:5173,http://localhost:5174"
    cors_allow_credentials: bool = True
    max_request_body_bytes: int = 262_144
    security_headers_enabled: bool = True
    # Only correct when TLS terminates in front of the API. Left off by default
    # because sending HSTS over plain HTTP is a promise the deployment cannot
    # keep, and browsers are entitled to ignore a header that arrives too late.
    hsts_enabled: bool = False
    hsts_max_age_seconds: int = 31_536_000

    # Rate limiting. Per user, per route class, in-process token buckets. The
    # limits differ by cost: an agent run spends model calls, a memory search
    # costs a database round trip, and a webhook spends a dispatch.
    rate_limit_enabled: bool = True
    rate_limit_agent_runs_per_minute: int = 20
    rate_limit_llm_per_minute: int = 30
    rate_limit_memory_search_per_minute: int = 120
    rate_limit_permission_requests_per_minute: int = 60
    rate_limit_scheduled_jobs_per_minute: int = 30
    # Refill interval shared by every bucket. One setting so a test can drain a
    # bucket deterministically instead of sleeping.
    rate_limit_window_seconds: float = 60.0
    #: Ceiling on distinct (scope, key) buckets held in memory. Bounds the
    #: rate limiter's own footprint against a caller cycling distinct keys.
    rate_limit_max_buckets: int = 20_000
    #: Entries retained in the in-process security audit ring. Bounded because an
    #: unbounded trail is a memory-exhaustion vector reachable by provoking denials.
    security_audit_capacity: int = 2_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def _check_always_on_bounds(self) -> "Settings":
        """Refuse a combination of Always-On settings that cannot be safe.

        These are checked at construction rather than at first use so that a bad
        deployment fails to boot rather than failing halfway through a dispatch.
        """
        if self.always_on_poll_interval_seconds <= 0:
            raise ValueError("always_on_poll_interval_seconds must be greater than zero")
        if self.always_on_poll_interval_seconds >= self.always_on_job_timeout_seconds:
            raise ValueError(
                "always_on_poll_interval_seconds must be less than "
                "always_on_job_timeout_seconds, otherwise a tick can outlive the "
                "execution it is waiting on"
            )
        if self.always_on_min_interval_seconds < 60:
            raise ValueError("always_on_min_interval_seconds must be at least 60")
        if self.always_on_max_concurrent_runs < 1:
            raise ValueError("always_on_max_concurrent_runs must be at least 1")
        if self.always_on_max_active_jobs_per_user < 1:
            raise ValueError("always_on_max_active_jobs_per_user must be at least 1")
        if self.always_on_max_events_per_minute < 1:
            raise ValueError("always_on_max_events_per_minute must be at least 1")
        if self.always_on_grace_seconds < 0:
            raise ValueError("always_on_grace_seconds must not be negative")
        if self.always_on_stale_execution_seconds <= self.always_on_job_timeout_seconds:
            raise ValueError(
                "always_on_stale_execution_seconds must exceed "
                "always_on_job_timeout_seconds, otherwise recovery would fail out "
                "executions that are still legitimately running"
            )
        if self.always_on_event_ingress_secret is not None:
            if len(self.always_on_event_ingress_secret) < 32:
                raise ValueError(
                    "always_on_event_ingress_secret must be at least 32 characters "
                    "when set"
                )
        return self

    @model_validator(mode="after")
    def _check_fail_closed(self) -> "Settings":
        """Refuse configurations that would quietly weaken a security control.

        Every one of these is a case where the deployment *looks* configured and
        is not: a default decision of ALLOW, an unbounded loop, a body limit that
        is not a limit. Raising here means the process refuses to boot, which is
        the only moment at which an operator is guaranteed to still be looking.
        """
        if self.trust_default_decision not in {"DENY", "ASK"}:
            # ALLOW is reachable from the environment, which would make the whole
            # policy layer a no-op that reads as configured.
            raise ValueError(
                "trust_default_decision must be DENY or ASK; ALLOW would make the "
                "Trust Engine rubber-stamp every call"
            )

        for name in (
            "agent_max_iterations",
            "agent_max_tool_calls",
            "agent_max_permission_requests",
            "agent_max_denied_actions",
            "orchestrator_max_tracked_runs",
            "agent_max_request_chars",
            "untrusted_data_max_chars",
            "memory_max_content_chars",
            "max_request_body_bytes",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be greater than zero")

        if self.agent_max_runtime_seconds < 1:
            raise ValueError("agent_max_runtime_seconds must be greater than zero")
        if self.permission_request_ttl_seconds < 1:
            raise ValueError("permission_request_ttl_seconds must be greater than zero")

        for name in (
            "rate_limit_agent_runs_per_minute",
            "rate_limit_llm_per_minute",
            "rate_limit_memory_search_per_minute",
            "rate_limit_permission_requests_per_minute",
            "rate_limit_scheduled_jobs_per_minute",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.rate_limit_window_seconds <= 0:
            raise ValueError("rate_limit_window_seconds must be greater than zero")
        if self.rate_limit_max_buckets < 1:
            raise ValueError("rate_limit_max_buckets must be at least 1")

        if self.security_audit_capacity < 1:
            raise ValueError("security_audit_capacity must be at least 1")
        if self.max_request_body_bytes < 1_024:
            # A body limit below 1 KiB cannot carry a legitimate agent request and
            # is almost certainly a units mistake rather than a policy choice.
            raise ValueError("max_request_body_bytes must be at least 1024")

        if self.hsts_max_age_seconds < 0:
            raise ValueError("hsts_max_age_seconds must not be negative")

        origins = [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]
        if "*" in origins:
            # Credentialed CORS with a wildcard is either rejected by browsers or,
            # worse, honoured by a proxy in front of us.
            raise ValueError(
                "cors_allowed_origins must not contain '*'; list explicit origins"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def disabled_skill_names(self) -> frozenset[str]:
        return frozenset(
            name.strip() for name in self.disabled_skills.split(",") if name.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
