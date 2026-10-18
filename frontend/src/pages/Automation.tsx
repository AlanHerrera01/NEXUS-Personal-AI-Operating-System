import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../services/api/apiClient';
import { alwaysOnApi } from '../services/api/alwaysOnApi';
import { PageShell } from '../components/ui/PageShell';
import type {
  CreateProactiveRule,
  CreateScheduledJob,
  JobExecution,
  ProactiveRule,
  ScheduledJob,
  ScheduledTriggerType,
} from '../types';

const TRIGGERS: { value: ScheduledTriggerType; label: string; hint: string }[] = [
  { value: 'ONCE', label: 'Once', hint: 'Runs a single time at a moment you pick.' },
  { value: 'INTERVAL', label: 'Every N', hint: 'Repeats on a fixed interval.' },
  { value: 'CRON', label: 'Cron', hint: 'Standard 5-field cron, e.g. 0 9 * * 1-5.' },
  { value: 'EVENT', label: 'On event', hint: 'Fires when a matching webhook event arrives.' },
];

const CONDITION_TYPES = [
  { value: 'DAILY_AT_TIME', label: 'Daily at a time' },
  { value: 'DAY_OF_WEEK', label: 'On certain weekdays' },
  { value: 'IDLE_FOR', label: 'After a period of inactivity' },
  { value: 'TASK_OVERDUE', label: 'When tasks are overdue' },
] as const;

const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

const JOB_STATUS_STYLES: Record<string, string> = {
  ACTIVE: 'bg-surface-container text-tertiary',
  PAUSED: 'bg-surface-container text-primary',
  COMPLETED: 'bg-surface-container text-outline',
  FAILED: 'bg-surface-container text-error',
  CANCELLED: 'bg-surface-container text-outline',
};

const EXECUTION_STATUS_STYLES: Record<string, string> = {
  QUEUED: 'bg-surface-container text-outline',
  RUNNING: 'bg-surface-container text-secondary',
  WAITING_PERMISSION: 'bg-surface-container text-primary',
  COMPLETED: 'bg-surface-container text-tertiary',
  FAILED: 'bg-surface-container text-error',
  SKIPPED: 'bg-surface-container text-outline',
  CANCELLED: 'bg-surface-container text-outline',
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong';
}

function localTimezone(): string {
  // The browser knows the user's zone; defaulting the form to it avoids the
  // common "why did this fire at 3am" report for a schedule entered as UTC.
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function describeTrigger(job: ScheduledJob): string {
  switch (job.trigger_type) {
    case 'CRON':
      return `cron ${job.cron_expression ?? '?'}`;
    case 'INTERVAL':
      return `every ${job.interval_seconds ?? '?'}s`;
    case 'EVENT':
      return 'on event';
    case 'ONCE':
      return 'once';
  }
}

function formatMoment(value: string | null): string {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '--';
  return parsed.toLocaleString();
}

export default function Automation() {
  const [tab, setTab] = useState<'schedules' | 'proactive'>('schedules');

  const tabClass = (active: boolean) =>
    `font-label-mono-xs text-label-mono-xs px-space-sm py-1.5 rounded transition-colors ${
      active
        ? 'bg-surface-container-high text-on-surface'
        : 'bg-surface-container text-on-surface-variant hover:text-on-surface'
    }`;

  return (
    <PageShell
      eyebrow="Configuration · Automation"
      title="Automation"
      description="Trabajo autónomo programado y reglas proactivas, siempre gobernadas por el Trust Engine."
      actions={
        <div className="flex gap-space-xs">
          <button onClick={() => setTab('schedules')} className={tabClass(tab === 'schedules')}>
            Schedules
          </button>
          <button onClick={() => setTab('proactive')} className={tabClass(tab === 'proactive')}>
            Proactive Rules
          </button>
        </div>
      }
    >
      {tab === 'schedules' ? <Schedules /> : <ProactiveRules />}
    </PageShell>
  );
}

function Schedules() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [executions, setExecutions] = useState<Record<string, JobExecution[]>>({});
  const [showForm, setShowForm] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setJobs(await alwaysOnApi.listJobs());
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // `cancelled` guards the classic setState-after-unmount leak: the list request
    // can still be in flight when the user switches tabs or navigates away.
    let cancelled = false;
    void (async () => {
      try {
        const rows = await alwaysOnApi.listJobs();
        if (!cancelled) {
          setJobs(rows);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const act = async (run: () => Promise<unknown>) => {
    try {
      await run();
      setError(null);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const toggleHistory = async (job: ScheduledJob) => {
    if (expanded === job.id) {
      setExpanded(null);
      return;
    }
    setExpanded(job.id);
    if (!executions[job.id]) {
      try {
        const rows = await alwaysOnApi.listExecutions(job.id);
        setExecutions((previous) => ({ ...previous, [job.id]: rows }));
      } catch (caught) {
        setError(errorMessage(caught));
      }
    }
  };

  return (
    <div className="space-y-4">
      {showForm ? (
        <CreateJobForm
          onCancel={() => setShowForm(false)}
          onCreated={async () => {
            setShowForm(false);
            await refresh();
          }}
        />
      ) : (
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-2 rounded bg-primary text-on-primary text-sm hover:bg-primary-container"
        >
          New schedule
        </button>
      )}

      {error && (
        <div className="p-3 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-outline text-sm">Loading schedules...</p>
      ) : jobs.length === 0 ? (
        <p className="text-outline text-sm">
          No schedules yet. A schedule creates an agent run at a chosen time or in
          response to an event.
        </p>
      ) : (
        <div className="space-y-2">
          {jobs.map((job) => (
            <div key={job.id} className="bg-surface-container-low border border-outline-variant/20 rounded">
              <div className="p-4 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-on-surface">{job.name}</span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        JOB_STATUS_STYLES[job.status] ?? 'bg-surface-container text-outline'
                      }`}
                    >
                      {job.status}
                    </span>
                  </div>
                  <p className="text-sm text-on-surface-variant mt-1">{describeTrigger(job)}</p>
                  <p className="text-xs text-outline mt-1">
                    {job.timezone} &middot; next {formatMoment(job.next_run_at)}
                    {job.last_error ? ` · last error: ${job.last_error}` : ''}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => void toggleHistory(job)}
                    className="px-3 py-1 rounded border border-outline-variant/40 text-sm hover:bg-surface-container-lowest"
                  >
                    {expanded === job.id ? 'Hide history' : 'History'}
                  </button>
                  {job.status === 'PAUSED' || job.status === 'FAILED' ? (
                    <button
                      onClick={() => void act(() => alwaysOnApi.resumeJob(job.id))}
                      className="px-3 py-1 rounded border border-outline-variant/40 text-sm hover:bg-surface-container-lowest"
                    >
                      Resume
                    </button>
                  ) : (
                    <button
                      onClick={() => void act(() => alwaysOnApi.pauseJob(job.id))}
                      className="px-3 py-1 rounded border border-outline-variant/40 text-sm hover:bg-surface-container-lowest"
                    >
                      Pause
                    </button>
                  )}
                  <button
                    onClick={() => void act(() => alwaysOnApi.deleteJob(job.id))}
                    className="px-3 py-1 rounded border border-error/40 text-sm text-error hover:bg-error-container/30"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {expanded === job.id && (
                <div className="border-t border-outline-variant/10 px-4 py-3 bg-surface-container-lowest">
                  {(executions[job.id] ?? []).length === 0 ? (
                    <p className="text-xs text-outline">No executions recorded yet.</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead className="text-outline">
                        <tr>
                          <th className="text-left py-1">Status</th>
                          <th className="text-left py-1">Scheduled for</th>
                          <th className="text-left py-1">Attempt</th>
                          <th className="text-left py-1">Outcome</th>
                          <th className="text-left py-1">Run</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(executions[job.id] ?? []).map((row) => (
                          <tr key={row.id} className="border-t border-outline-variant/20">
                            <td className="py-1 pr-2">
                              <span
                                className={`px-2 py-0.5 rounded-full font-medium ${
                                  EXECUTION_STATUS_STYLES[row.status] ??
                                  'bg-surface-container text-outline'
                                }`}
                              >
                                {row.status}
                              </span>
                            </td>
                            <td className="py-1 pr-2">{formatMoment(row.scheduled_for)}</td>
                            <td className="py-1 pr-2">{row.attempt}</td>
                            <td className="py-1 pr-2 text-on-surface-variant">
                              {row.error_message ?? row.result_summary ?? '--'}
                            </td>
                            <td className="py-1 pr-2">
                              {row.agent_run_id ? (
                                <a className="text-secondary hover:underline" href={`/runs/${row.agent_run_id}`}>
                                  view
                                </a>
                              ) : (
                                '--'
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateJobForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => Promise<void>;
}) {
  const [agentId, setAgentId] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [triggerType, setTriggerType] = useState<ScheduledTriggerType>('CRON');
  const [timezone, setTimezone] = useState(localTimezone());
  const [cron, setCron] = useState('0 9 * * 1-5');
  const [intervalSeconds, setIntervalSeconds] = useState(3600);
  const [runAt, setRunAt] = useState('');
  const [prompt, setPrompt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const activeTrigger = TRIGGERS.find((t) => t.value === triggerType);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    // Only send the field that belongs to the chosen trigger. Sending all of them
    // would leave a stale cron string attached to an interval job.
    const body: CreateScheduledJob = {
      agent_id: agentId.trim(),
      name: name.trim(),
      description: description.trim(),
      trigger_type: triggerType,
      timezone: timezone.trim() || 'UTC',
      payload: prompt.trim() ? { prompt: prompt.trim() } : {},
    };
    if (triggerType === 'CRON') body.cron_expression = cron.trim();
    if (triggerType === 'INTERVAL') body.interval_seconds = Number(intervalSeconds);
    if (triggerType === 'ONCE') {
      if (!runAt) {
        setError('Pick a date and time for a one-time schedule.');
        setSaving(false);
        return;
      }
      body.run_at = new Date(runAt).toISOString();
    }

    try {
      await alwaysOnApi.createJob(body);
      await onCreated();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="bg-surface-container-low border border-outline-variant/20 rounded p-4 space-y-3">
      <h2 className="font-semibold text-on-surface">New schedule</h2>

      {error && (
        <div className="p-2 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Agent ID</span>
          <input
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder="uuid of the agent to run"
          />
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder="Morning briefing"
          />
        </label>
      </div>

      <label className="block text-sm">
        <span className="block text-on-surface-variant mb-1">Description</span>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
        />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Trigger</span>
          <select
            value={triggerType}
            onChange={(e) => setTriggerType(e.target.value as ScheduledTriggerType)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          >
            {TRIGGERS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Timezone</span>
          <input
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder="Europe/Madrid"
          />
        </label>
      </div>

      {activeTrigger && (
        <p className="text-xs text-outline">{activeTrigger.hint}</p>
      )}

      {triggerType === 'CRON' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">Cron expression</span>
          <input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm font-code-base"
            placeholder="0 9 * * 1-5"
          />
        </label>
      )}

      {triggerType === 'INTERVAL' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">Every (seconds)</span>
          <input
            type="number"
            min={60}
            value={intervalSeconds}
            onChange={(e) => setIntervalSeconds(Number(e.target.value))}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      )}

      {triggerType === 'ONCE' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">Run at</span>
          <input
            type="datetime-local"
            value={runAt}
            onChange={(e) => setRunAt(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      )}

      <label className="block text-sm">
        <span className="block text-on-surface-variant mb-1">Prompt for the agent run</span>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          placeholder="What should the agent do when this fires?"
        />
      </label>

      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 rounded bg-primary text-on-primary text-sm disabled:opacity-50"
        >
          {saving ? 'Creating...' : 'Create schedule'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 rounded border border-outline-variant/40 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function ProactiveRules() {
  const [rules, setRules] = useState<ProactiveRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setRules(await alwaysOnApi.listRules());
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Same unmount guard as the schedules tab.
    let cancelled = false;
    void (async () => {
      try {
        const rows = await alwaysOnApi.listRules();
        if (!cancelled) {
          setRules(rows);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const act = async (run: () => Promise<unknown>) => {
    try {
      await run();
      setError(null);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <div className="space-y-4">
      {showForm ? (
        <CreateRuleForm
          onCancel={() => setShowForm(false)}
          onCreated={async () => {
            setShowForm(false);
            await refresh();
          }}
        />
      ) : (
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-2 rounded bg-primary text-on-primary text-sm hover:bg-primary-container"
        >
          New rule
        </button>
      )}

      {error && (
        <div className="p-3 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-outline text-sm">Loading rules...</p>
      ) : rules.length === 0 ? (
        <p className="text-outline text-sm">
          No proactive rules yet. A rule lets the agent start something on its own
          under a condition you define, subject to a cooldown.
        </p>
      ) : (
        <div className="space-y-2">
          {rules.map((rule) => (
            <div key={rule.id} className="bg-surface-container-low border border-outline-variant/20 rounded p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-on-surface">{rule.name}</span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        rule.enabled
                          ? 'bg-surface-container text-tertiary'
                          : 'bg-surface-container text-outline'
                      }`}
                    >
                      {rule.enabled ? 'enabled' : 'disabled'}
                    </span>
                  </div>
                  <p className="text-sm text-on-surface-variant mt-1">
                    condition <code className="text-xs">{String(rule.condition.type)}</code>{' '}
                    &rarr; action <code className="text-xs">{String(rule.action.type)}</code>
                  </p>
                  <p className="text-xs text-outline mt-1">
                    fired {rule.trigger_count} time{rule.trigger_count === 1 ? '' : 's'}
                    {rule.last_triggered_at
                      ? ` · last ${formatMoment(rule.last_triggered_at)}`
                      : ''}{' '}
                    &middot; cooldown {rule.cooldown_seconds}s
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() =>
                      void act(() =>
                        rule.enabled
                          ? alwaysOnApi.disableRule(rule.id)
                          : alwaysOnApi.enableRule(rule.id),
                      )
                    }
                    className="px-3 py-1 rounded border border-outline-variant/40 text-sm hover:bg-surface-container-lowest"
                  >
                    {rule.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    onClick={() => void act(() => alwaysOnApi.deleteRule(rule.id))}
                    className="px-3 py-1 rounded border border-error/40 text-sm text-error hover:bg-error-container/30"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateRuleForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => Promise<void>;
}) {
  const [agentId, setAgentId] = useState('');
  const [name, setName] = useState('');
  const [conditionType, setConditionType] = useState<string>(CONDITION_TYPES[0].value);
  const [at, setAt] = useState('09:00');
  const [days, setDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri']);
  const [minutes, setMinutes] = useState(60);
  const [minCount, setMinCount] = useState(1);
  const [actionType, setActionType] = useState('SUGGEST');
  const [message, setMessage] = useState('');
  const [cooldown, setCooldown] = useState(3600);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const buildCondition = (): Record<string, unknown> => {
    const timezone = localTimezone();
    if (conditionType === 'DAILY_AT_TIME') return { type: conditionType, at, timezone };
    if (conditionType === 'DAY_OF_WEEK') return { type: conditionType, days, at, timezone };
    if (conditionType === 'IDLE_FOR') return { type: conditionType, minutes };
    return { type: 'TASK_OVERDUE', min_count: minCount };
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    const body: CreateProactiveRule = {
      agent_id: agentId.trim(),
      name: name.trim(),
      condition: buildCondition(),
      action: { type: actionType, message: message.trim() },
      cooldown_seconds: Number(cooldown),
      enabled: true,
    };

    try {
      await alwaysOnApi.createRule(body);
      await onCreated();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="bg-surface-container-low border border-outline-variant/20 rounded p-4 space-y-3">
      <h2 className="font-semibold text-on-surface">New proactive rule</h2>

      {error && (
        <div className="p-2 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Agent ID</span>
          <input
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder="Nudge me after a quiet hour"
          />
        </label>
      </div>

      <label className="block text-sm">
        <span className="block text-on-surface-variant mb-1">Condition</span>
        <select
          value={conditionType}
          onChange={(e) => setConditionType(e.target.value)}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
        >
          {CONDITION_TYPES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </label>

      {(conditionType === 'DAILY_AT_TIME' || conditionType === 'DAY_OF_WEEK') && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">Time (HH:MM)</span>
          <input
            value={at}
            onChange={(e) => setAt(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      )}

      {conditionType === 'DAY_OF_WEEK' && (
        <div className="text-sm">
          <span className="block text-on-surface-variant mb-1">Days</span>
          <div className="flex gap-2">
            {WEEKDAYS.map((day) => (
              <label key={day} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={days.includes(day)}
                  onChange={(e) =>
                    setDays((previous) =>
                      e.target.checked ? [...previous, day] : previous.filter((d) => d !== day),
                    )
                  }
                />
                {day}
              </label>
            ))}
          </div>
        </div>
      )}

      {conditionType === 'IDLE_FOR' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">Idle for (minutes)</span>
          <input
            type="number"
            min={1}
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      )}

      {conditionType === 'TASK_OVERDUE' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">Overdue tasks at least</span>
          <input
            type="number"
            min={1}
            value={minCount}
            onChange={(e) => setMinCount(Number(e.target.value))}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Action</span>
          <select
            value={actionType}
            onChange={(e) => setActionType(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          >
            <option value="SUGGEST">Suggest (surface it, do not act)</option>
            <option value="RUN_AGENT">Run agent</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">Cooldown (seconds)</span>
          <input
            type="number"
            min={60}
            max={86400}
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      </div>

      <label className="block text-sm">
        <span className="block text-on-surface-variant mb-1">Message</span>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          required
          rows={2}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          placeholder="What the agent should say or do"
        />
      </label>

      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 rounded bg-primary text-on-primary text-sm disabled:opacity-50"
        >
          {saving ? 'Creating...' : 'Create rule'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 rounded border border-outline-variant/40 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
