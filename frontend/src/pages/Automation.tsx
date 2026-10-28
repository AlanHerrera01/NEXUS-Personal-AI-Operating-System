import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../hooks/useI18n';
import type { InterpolationValues, MessageKey } from '../i18n/types';
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

/** The translator, shaped so helpers outside the component can take it as an argument. */
type Translate = (key: MessageKey, values?: InterpolationValues) => string;

/* The form options carry a key rather than a label so the lists stay module
   constants: they are translated where they render, not when they are built. */
const TRIGGERS: { value: ScheduledTriggerType; labelKey: MessageKey; hintKey: MessageKey }[] = [
  {
    value: 'ONCE',
    labelKey: 'pages.automation.triggers.once',
    hintKey: 'pages.automation.triggers.onceHint',
  },
  {
    value: 'INTERVAL',
    labelKey: 'pages.automation.triggers.everyN',
    hintKey: 'pages.automation.triggers.everyNHint',
  },
  {
    value: 'CRON',
    labelKey: 'pages.automation.triggers.cron',
    hintKey: 'pages.automation.triggers.cronHint',
  },
  {
    value: 'EVENT',
    labelKey: 'pages.automation.triggers.onEvent',
    hintKey: 'pages.automation.triggers.onEventHint',
  },
];

const CONDITION_TYPES: { value: string; labelKey: MessageKey }[] = [
  { value: 'DAILY_AT_TIME', labelKey: 'pages.automation.rules.form.dailyAtTime' },
  { value: 'DAY_OF_WEEK', labelKey: 'pages.automation.rules.form.dayOfWeek' },
  { value: 'IDLE_FOR', labelKey: 'pages.automation.rules.form.idleFor' },
  { value: 'TASK_OVERDUE', labelKey: 'pages.automation.rules.form.taskOverdue' },
];

const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

/* The codes travel to the backend; only their labels are interface copy. */
const WEEKDAY_LABELS: Record<string, MessageKey> = {
  mon: 'pages.automation.weekdays.mon',
  tue: 'pages.automation.weekdays.tue',
  wed: 'pages.automation.weekdays.wed',
  thu: 'pages.automation.weekdays.thu',
  fri: 'pages.automation.weekdays.fri',
  sat: 'pages.automation.weekdays.sat',
  sun: 'pages.automation.weekdays.sun',
};

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

function errorMessage(error: unknown, t: Translate): string {
  // The backend's own message is data and ships as it arrives; only the
  // fallback for a thrown value that is not an Error is interface copy.
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return t('pages.automation.errors.generic');
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

function describeTrigger(job: ScheduledJob, t: Translate): string {
  switch (job.trigger_type) {
    case 'CRON':
      return t('pages.automation.triggers.describeCron', {
        expression: job.cron_expression ?? '?',
      });
    case 'INTERVAL':
      return t('pages.automation.triggers.describeInterval', {
        seconds: job.interval_seconds ?? '?',
      });
    case 'EVENT':
      return t('pages.automation.triggers.describeEvent');
    case 'ONCE':
      return t('pages.automation.triggers.describeOnce');
  }
}

export default function Automation() {
  const { t } = useI18n();
  const [tab, setTab] = useState<'schedules' | 'proactive'>('schedules');

  const tabClass = (active: boolean) =>
    `font-label-mono-xs text-label-mono-xs px-space-sm py-1.5 rounded transition-colors ${
      active
        ? 'bg-surface-container-high text-on-surface'
        : 'bg-surface-container text-on-surface-variant hover:text-on-surface'
    }`;

  return (
    <PageShell
      eyebrow={t('pages.automation.eyebrow')}
      title={t('pages.automation.title')}
      description={t('pages.automation.description')}
      actions={
        <div className="flex gap-space-xs">
          <button onClick={() => setTab('schedules')} className={tabClass(tab === 'schedules')}>
            {t('pages.automation.tabs.schedules')}
          </button>
          <button onClick={() => setTab('proactive')} className={tabClass(tab === 'proactive')}>
            {t('pages.automation.tabs.proactiveRules')}
          </button>
        </div>
      }
    >
      {tab === 'schedules' ? <Schedules /> : <ProactiveRules />}
    </PageShell>
  );
}

function Schedules() {
  const { t, formatDateTime } = useI18n();
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
      setError(errorMessage(caught, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

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
        if (!cancelled) setError(errorMessage(caught, t));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const act = async (run: () => Promise<unknown>) => {
    try {
      await run();
      setError(null);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught, t));
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
        setError(errorMessage(caught, t));
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
          {t('pages.automation.schedules.new')}
        </button>
      )}

      {error && (
        <div className="p-3 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-outline text-sm">{t('pages.automation.schedules.loading')}</p>
      ) : jobs.length === 0 ? (
        <p className="text-outline text-sm">{t('pages.automation.schedules.empty')}</p>
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
                  <p className="text-sm text-on-surface-variant mt-1">{describeTrigger(job, t)}</p>
                  <p className="text-xs text-outline mt-1">
                    {t('pages.automation.schedules.meta', {
                      timezone: job.timezone,
                      next: formatDateTime(job.next_run_at),
                    })}
                    {job.last_error
                      ? t('pages.automation.schedules.lastError', { message: job.last_error })
                      : ''}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => void toggleHistory(job)}
                    className="px-3 py-1 rounded border border-outline-variant/40 text-sm hover:bg-surface-container-lowest"
                  >
                    {expanded === job.id
                      ? t('pages.automation.schedules.hideHistory')
                      : t('pages.automation.schedules.history')}
                  </button>
                  {job.status === 'PAUSED' || job.status === 'FAILED' ? (
                    <button
                      onClick={() => void act(() => alwaysOnApi.resumeJob(job.id))}
                      className="px-3 py-1 rounded border border-outline-variant/40 text-sm hover:bg-surface-container-lowest"
                    >
                      {t('pages.automation.schedules.resume')}
                    </button>
                  ) : (
                    <button
                      onClick={() => void act(() => alwaysOnApi.pauseJob(job.id))}
                      className="px-3 py-1 rounded border border-outline-variant/40 text-sm hover:bg-surface-container-lowest"
                    >
                      {t('pages.automation.schedules.pause')}
                    </button>
                  )}
                  <button
                    onClick={() => void act(() => alwaysOnApi.deleteJob(job.id))}
                    className="px-3 py-1 rounded border border-error/40 text-sm text-error hover:bg-error-container/30"
                  >
                    {t('common.delete')}
                  </button>
                </div>
              </div>

              {expanded === job.id && (
                <div className="border-t border-outline-variant/10 px-4 py-3 bg-surface-container-lowest">
                  {(executions[job.id] ?? []).length === 0 ? (
                    <p className="text-xs text-outline">{t('pages.automation.schedules.noExecutions')}</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead className="text-outline">
                        <tr>
                          <th className="text-left py-1">{t('common.status')}</th>
                          <th className="text-left py-1">{t('pages.automation.schedules.table.scheduledFor')}</th>
                          <th className="text-left py-1">{t('pages.automation.schedules.table.attempt')}</th>
                          <th className="text-left py-1">{t('pages.automation.schedules.table.outcome')}</th>
                          <th className="text-left py-1">{t('pages.automation.schedules.table.run')}</th>
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
                            <td className="py-1 pr-2">{formatDateTime(row.scheduled_for)}</td>
                            <td className="py-1 pr-2">{row.attempt}</td>
                            <td className="py-1 pr-2 text-on-surface-variant">
                              {row.error_message ?? row.result_summary ?? '--'}
                            </td>
                            <td className="py-1 pr-2">
                              {row.agent_run_id ? (
                                <a className="text-secondary hover:underline" href={`/runs/${row.agent_run_id}`}>
                                  {t('pages.automation.schedules.table.view')}
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
  const { t } = useI18n();
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

  const activeTrigger = TRIGGERS.find((trigger) => trigger.value === triggerType);

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
        setError(t('pages.automation.schedules.form.pickDate'));
        setSaving(false);
        return;
      }
      // `runAt` is a payload value, not display, so it stays an ISO string.
      body.run_at = new Date(runAt).toISOString();
    }

    try {
      await alwaysOnApi.createJob(body);
      await onCreated();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="bg-surface-container-low border border-outline-variant/20 rounded p-4 space-y-3">
      <h2 className="font-semibold text-on-surface">{t('pages.automation.schedules.new')}</h2>

      {error && (
        <div className="p-2 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.schedules.form.agentId')}
          </span>
          <input
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder={t('pages.automation.schedules.form.agentIdPlaceholder')}
          />
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">{t('common.name')}</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder={t('pages.automation.schedules.form.namePlaceholder')}
          />
        </label>
      </div>

      <label className="block text-sm">
        <span className="block text-on-surface-variant mb-1">{t('common.description')}</span>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
        />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.schedules.form.trigger')}
          </span>
          <select
            value={triggerType}
            onChange={(e) => setTriggerType(e.target.value as ScheduledTriggerType)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          >
            {TRIGGERS.map((trigger) => (
              <option key={trigger.value} value={trigger.value}>
                {t(trigger.labelKey)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.schedules.form.timezone')}
          </span>
          <input
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder={t('pages.automation.schedules.form.timezonePlaceholder')}
          />
        </label>
      </div>

      {activeTrigger && (
        <p className="text-xs text-outline">{t(activeTrigger.hintKey)}</p>
      )}

      {triggerType === 'CRON' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.schedules.form.cronExpression')}
          </span>
          <input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm font-code-base"
            placeholder={t('pages.automation.schedules.form.cronPlaceholder')}
          />
        </label>
      )}

      {triggerType === 'INTERVAL' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.schedules.form.everySeconds')}
          </span>
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
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.schedules.form.runAt')}
          </span>
          <input
            type="datetime-local"
            value={runAt}
            onChange={(e) => setRunAt(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      )}

      <label className="block text-sm">
        <span className="block text-on-surface-variant mb-1">
          {t('pages.automation.schedules.form.prompt')}
        </span>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          placeholder={t('pages.automation.schedules.form.promptPlaceholder')}
        />
      </label>

      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 rounded bg-primary text-on-primary text-sm disabled:opacity-50"
        >
          {saving ? t('pages.automation.schedules.form.creating') : t('pages.automation.schedules.form.create')}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 rounded border border-outline-variant/40 text-sm"
        >
          {t('common.cancel')}
        </button>
      </div>
    </form>
  );
}

function ProactiveRules() {
  const { t, formatDateTime, formatNumber } = useI18n();
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
      setError(errorMessage(caught, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

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
        if (!cancelled) setError(errorMessage(caught, t));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const act = async (run: () => Promise<unknown>) => {
    try {
      await run();
      setError(null);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught, t));
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
          {t('pages.automation.rules.new')}
        </button>
      )}

      {error && (
        <div className="p-3 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-outline text-sm">{t('pages.automation.rules.loading')}</p>
      ) : rules.length === 0 ? (
        <p className="text-outline text-sm">{t('pages.automation.rules.empty')}</p>
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
                      {rule.enabled
                        ? t('pages.automation.rules.enabled')
                        : t('pages.automation.rules.disabled')}
                    </span>
                  </div>
                  <p className="text-sm text-on-surface-variant mt-1">
                    {t('pages.automation.rules.conditionLabel')}{' '}
                    <code className="text-xs">{String(rule.condition.type)}</code>{' '}
                    &rarr; {t('pages.automation.rules.actionLabel')}{' '}
                    <code className="text-xs">{String(rule.action.type)}</code>
                  </p>
                  <p className="text-xs text-outline mt-1">
                    {rule.trigger_count === 1
                      ? t('pages.automation.rules.firedOne', {
                          count: formatNumber(rule.trigger_count),
                        })
                      : t('pages.automation.rules.firedMany', {
                          count: formatNumber(rule.trigger_count),
                        })}
                    {rule.last_triggered_at
                      ? t('pages.automation.rules.lastTriggered', {
                          moment: formatDateTime(rule.last_triggered_at),
                        })
                      : ''}{' '}
                    {t('pages.automation.rules.cooldown', { seconds: rule.cooldown_seconds })}
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
                    {rule.enabled
                      ? t('pages.automation.rules.disable')
                      : t('pages.automation.rules.enable')}
                  </button>
                  <button
                    onClick={() => void act(() => alwaysOnApi.deleteRule(rule.id))}
                    className="px-3 py-1 rounded border border-error/40 text-sm text-error hover:bg-error-container/30"
                  >
                    {t('common.delete')}
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
  const { t } = useI18n();
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
      setError(errorMessage(caught, t));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="bg-surface-container-low border border-outline-variant/20 rounded p-4 space-y-3">
      <h2 className="font-semibold text-on-surface">{t('pages.automation.rules.form.title')}</h2>

      {error && (
        <div className="p-2 rounded bg-error-container/30 border border-error/40 text-error text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.rules.form.agentId')}
          </span>
          <input
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">{t('common.name')}</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
            placeholder={t('pages.automation.rules.form.namePlaceholder')}
          />
        </label>
      </div>

      <label className="block text-sm">
        <span className="block text-on-surface-variant mb-1">
          {t('pages.automation.rules.form.condition')}
        </span>
        <select
          value={conditionType}
          onChange={(e) => setConditionType(e.target.value)}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
        >
          {CONDITION_TYPES.map((condition) => (
            <option key={condition.value} value={condition.value}>
              {t(condition.labelKey)}
            </option>
          ))}
        </select>
      </label>

      {(conditionType === 'DAILY_AT_TIME' || conditionType === 'DAY_OF_WEEK') && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.rules.form.time')}
          </span>
          <input
            value={at}
            onChange={(e) => setAt(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          />
        </label>
      )}

      {conditionType === 'DAY_OF_WEEK' && (
        <div className="text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.rules.form.days')}
          </span>
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
                {t(WEEKDAY_LABELS[day])}
              </label>
            ))}
          </div>
        </div>
      )}

      {conditionType === 'IDLE_FOR' && (
        <label className="block text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.rules.form.idleForMinutes')}
          </span>
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
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.rules.form.overdueAtLeast')}
          </span>
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
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.rules.form.action')}
          </span>
          <select
            value={actionType}
            onChange={(e) => setActionType(e.target.value)}
            className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          >
            <option value="SUGGEST">{t('pages.automation.rules.form.actionSuggest')}</option>
            <option value="RUN_AGENT">{t('pages.automation.rules.form.actionRunAgent')}</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-on-surface-variant mb-1">
            {t('pages.automation.rules.form.cooldown')}
          </span>
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
        <span className="block text-on-surface-variant mb-1">
          {t('pages.automation.rules.form.message')}
        </span>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          required
          rows={2}
          className="w-full px-2 py-1 border border-outline-variant/40 rounded text-sm"
          placeholder={t('pages.automation.rules.form.messagePlaceholder')}
        />
      </label>

      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 rounded bg-primary text-on-primary text-sm disabled:opacity-50"
        >
          {saving ? t('pages.automation.rules.form.creating') : t('pages.automation.rules.form.create')}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 rounded border border-outline-variant/40 text-sm"
        >
          {t('common.cancel')}
        </button>
      </div>
    </form>
  );
}
