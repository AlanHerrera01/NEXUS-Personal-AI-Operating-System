# Always-On

Phase 12 lets the agent act without being talked to. A schedule or an inbound
event creates an `AgentRun` on its own, and the run goes through exactly the same
controlled pipeline as one started from the chat box.

## The point of the design

The hard part of "always on" is not the timer. It is that unattended work has a
much worse failure mode than supervised work: if the loop is wrong, it repeats
the mistake every hour while nobody is looking. Three decisions follow from that,
and everything else is detail.

**Scheduling a job grants no authority.** Creating a cron job is not permission
to run the action it names. Every triggered execution re-enters the pipeline and
is re-decided by the Trust Engine, using the orchestrator built for interactive
runs, so one-shot authorization, tool policies, and human-in-the-loop approval
apply identically. A schedule decides *when the agent wakes up*, never *what it is
allowed to do*.

**Exactly once, or visibly twice.** A tick can overlap with the next tick, and
more than one process can poll the same database. Correctness therefore lives in
the database rather than in the scheduler: a unique constraint on
`(scheduled_job_id, scheduled_for)` means a due slot can only ever produce one
execution row, and claiming one is a compare-and-set from `QUEUED` to `RUNNING`.
A losing racer sees "not claimed" and moves on. There is no lock held in memory
because in-memory locks are per-process and therefore useless the moment there
is a second process.

**A crashed run must not look healthy.** Recovery fails any `RUNNING`
execution older than `always_on_stale_execution_seconds` rather than retrying it.
Automatic retry of an unattended side effect is the one behaviour that turns a
transient error into a duplicated action. The execution is left `FAILED` with the
reason recorded, which is also what the user needs in order to trust the history.

`WAITING_PERMISSION` is deliberately exempt from recovery. A run parked on a
human decision is not stale; failing it would destroy work the user was in the
middle of approving. It stays open until it is approved, rejected, or expires.

## Proactivity is deterministic

`ProactiveRule` conditions are a closed set — `DAILY_AT_TIME`, `DAY_OF_WEEK`,
`IDLE_FOR`, `TASK_OVERDUE` — evaluated by pure functions over the clock and
counts the caller already has. No model is involved.

That is load-bearing rather than a performance shortcut. A proactive system that
asks a model "is this a good moment to interrupt?" spends money on every poll,
can loop, and cannot be tested against a known answer. An unrecognised condition
type raises at rule creation instead of silently evaluating false, because a typo
that never fires is the worst possible outcome for a feature whose whole value is
showing up unprompted.

Each time-based condition stays true for the rest of the day once its moment has
passed, rather than true at one instant. A scheduler polling every few seconds
would otherwise have to hit an exact millisecond. The rule's cooldown is what
turns "still true" into "fire once".

## Scheduling

The schedule is rolled forward at dispatch time, not on success. A run that then
fails does not strand the schedule, and a slow run never blocks its own next
occurrence. This is why `try_advance_schedule` is a separate compare-and-set from
the execution claim: the claim decides who runs, the schedule decides when, and
they are allowed to disagree about whether the run succeeded.

A `ONCE` job that has fired and has no further occurrences is moved to
`COMPLETED` rather than left `ACTIVE` with a null `next_run_at`, which would be
the worst of both states — not due, not terminal, never runnable.

## Cron

A five-field parser with no external dependency, evaluated on naive local
wall-clock datetimes inside the requested IANA zone and converted to UTC only at
the boundary. Doing the arithmetic in UTC would make "09:00 every weekday" drift
by an hour twice a year.

When both day-of-month and day-of-week are restricted, the day matches if
**either** field matches, as in Vixie cron. So `0 0 13 * 5` fires on the 13th
of every month *and* on every Friday. The opposite reading is the most common way
a hand-written cron parser goes wrong: the expression still validates and still
looks reasonable, it just fires about once every 28 months.

`7` is accepted as Sunday alongside `0`. Ranges, lists, and `*` are supported;
`L`, `#`, and `@daily` are not, and are rejected at creation with a specific
message rather than silently misfiring later.

## Webhook ingress

`POST /api/v1/events/trigger` accepts an external event and matches it against
event-triggered jobs.

Authentication is a shared secret compared with `secrets.compare_digest`, read
from `X-NEXUS-Ingress-Secret`. If the secret is unset the endpoint is **closed**
and rejects every request: a missing secret fails shut rather than open. The
check runs *before* the feature flag, so a disabled-but-reachable ingress still
answers `401` rather than disclosing whether Always-On is enabled. CORS does not
expose this header to browsers, so a web page cannot drive the ingress.

Events are idempotent on `idempotency_key`. A repeat returns the original event
and reports it as a duplicate rather than dispatching a second time.

## Ownership without authentication

There is no authentication layer yet, so Always-On rows are owned by a fixed
local UUID (`LOCAL_USER_ID`). It is taken from server configuration only: never
from a header, query parameter, or request body. Accepting a caller-supplied user
id would make every row trivially forgeable by anyone who can reach the API, so
the routes have no way to express "act as someone else".

This is deliberately not a substitute for authentication. Before this is exposed
beyond a single-user machine, the identity comes from the session and this UUID
becomes its subject.

## Feature flag

`always_on_enabled` defaults to `false`. The routes stay mounted so existing
schedules can be inspected, paused, and deleted without turning the feature on.
Operations that would *start work* — creating a job, ingesting an event, creating
a rule — return `503`. That keeps the flag about creating unattended work rather
than about hiding the UI.

## Configuration

```text
always_on_enabled=false
always_on_event_ingress_secret=             # unset means ingress is closed
always_on_poll_interval_seconds=5
always_on_max_jobs_per_tick=50
always_on_job_timeout_seconds=300
always_on_stale_execution_seconds=1800      # must exceed the timeout
always_on_grace_seconds=900                 # older occurrence is skipped, not replayed
always_on_max_concurrent_runs=3
always_on_min_interval_seconds=300          # floor on INTERVAL jobs
always_on_max_active_jobs_per_user=20
always_on_max_retries=2
always_on_max_events_per_minute=60
always_on_max_jobs_per_event=20
always_on_max_proactive_rules_per_user=50
```

Two of these bounds are worth calling out. `always_on_min_interval_seconds`
refuses a sub-5-minute interval at creation rather than rate-limiting it later,
because a 1-second interval is a denial-of-service button that spends model calls
and opens runs forever. `always_on_grace_seconds` is the catch-up policy: an
occurrence missed by longer than this is recorded `SKIPPED` and rescheduled from
now, because replaying a week of missed 5-minute intervals would be a stampede.

The stale threshold is validated against the job timeout at startup, because the
combination in which recovery is *shorter* than a legitimate run would fail
executions that are still working.

## API

```text
GET    /api/v1/scheduled-jobs                 list, ?status=
POST   /api/v1/scheduled-jobs                 create
GET    /api/v1/scheduled-jobs/{id}
PATCH  /api/v1/scheduled-jobs/{id}
POST   /api/v1/scheduled-jobs/{id}/pause
POST   /api/v1/scheduled-jobs/{id}/resume
DELETE /api/v1/scheduled-jobs/{id}
GET    /api/v1/scheduled-jobs/{id}/executions
GET    /api/v1/scheduled-jobs/executions/{execution_id}

POST   /api/v1/events/trigger                 X-NEXUS-Ingress-Secret

GET    /api/v1/proactive-rules                ?enabled_only=
POST   /api/v1/proactive-rules
GET    /api/v1/proactive-rules/{id}
POST   /api/v1/proactive-rules/{id}/enable
POST   /api/v1/proactive-rules/{id}/disable
DELETE /api/v1/proactive-rules/{id}           204, no body
```

## HITL on an unattended run

A background run that hits `ASK` parks in `WAITING_PERMISSION` exactly like an
interactive one. Approving or rejecting through the permission endpoints calls
`JobExecutionCoordinator.reconcile`, which resumes the orchestrator only when the
decision actually permits it. A rejected approval does not resume the agent.

## Known gaps

- **Agents are chosen by id.** There is no endpoint to list agents, so the
  Automation form takes a raw agent UUID. A listing endpoint is needed before the
  picker can be a dropdown.
- **Two of the four proactive conditions can never fire yet.** The tick builds
  its `ProactiveContext` with `last_activity_at=None` and both task counts at
  zero, so `IDLE_FOR` (no recorded activity to judge against) and `TASK_OVERDUE`
  (no overdue tasks) always evaluate false. Only the two clock-based conditions
  work. This is deliberate rather than a silent lie — the evaluation service
  reports "no overdue tasks (threshold 1)" instead of pretending to have checked
  — but the UI currently offers conditions that will never fire.
- **Single node.** Correctness is multi-process safe, but nothing coordinates
  ticks, so several pollers simply divide the work.
- **`alembic check` reports drift** in `memories`, `permission_requests`, and
  `permissions` that predates this phase.