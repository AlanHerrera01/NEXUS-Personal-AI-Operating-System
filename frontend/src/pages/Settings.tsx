import { useState, type ReactNode } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { useI18n } from '../hooks/useI18n';
import { useOverview } from '../hooks/useOverview';
import { healthApi } from '../services/api/healthApi';
import { memoryApi } from '../services/api/memoryApi';
import { settingsApi } from '../services/api/settingsApi';
import { API_BASE_URL } from '../services/api/apiClient';
import { ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { MessageKey } from '../i18n/types';
import type { RuntimeSettings, RuntimeSettingsUpdate } from '../types';

type TabKey = 'general' | 'model' | 'memory' | 'runtime' | 'trust' | 'about';

/* The tabs carry a key rather than a label so the list stays a module constant:
   translating at render is what lets the switch relabel them without a rebuild. */
const TABS: { key: TabKey; labelKey: MessageKey; icon: string }[] = [
  { key: 'general', labelKey: 'pages.settings.tabs.general', icon: 'tune' },
  { key: 'model', labelKey: 'pages.settings.tabs.model', icon: 'neurology' },
  { key: 'memory', labelKey: 'pages.settings.tabs.memory', icon: 'memory' },
  { key: 'runtime', labelKey: 'pages.settings.tabs.runtime', icon: 'deployed_code' },
  { key: 'trust', labelKey: 'pages.settings.tabs.trust', icon: 'shield' },
  { key: 'about', labelKey: 'pages.settings.tabs.about', icon: 'info' },
];

function formatUptime(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return '--';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function SectionCard({
  icon,
  iconTone = 'text-secondary',
  title,
  subtitle,
  badge,
  children,
}: {
  icon: string;
  iconTone?: string;
  title: string;
  subtitle: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="bg-surface-container rounded-xl p-space-lg flex flex-col gap-space-lg shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm">
        <div className="flex items-center gap-space-sm">
          <div className="w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center shrink-0">
            <span className={`material-symbols-outlined text-[20px] ${iconTone}`}>{icon}</span>
          </div>
          <div>
            <h2 className="font-headline-sm text-headline-sm font-semibold text-on-surface">{title}</h2>
            <p className="font-body-sm text-body-sm text-on-surface-variant">{subtitle}</p>
          </div>
        </div>
        {badge}
      </div>
      {children}
    </section>
  );
}

function ReadOnlyValue({ value, mono = false }: { value: ReactNode; mono?: boolean }) {
  return (
    <div
      className={`flex items-center gap-space-xs bg-surface-container-lowest px-space-md py-2 rounded-lg shadow-sm ${
        mono ? 'font-code-base text-code-base' : 'font-body-md text-body-md'
      } text-on-surface`}
    >
      {value}
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  hint,
  badge,
  mono,
  type = 'text',
  min,
  max,
  step,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  badge?: ReactNode;
  mono?: boolean;
  type?: string;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
          {label}
        </label>
        {badge}
      </div>
      <input
        type={type}
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={`w-full bg-surface-container-lowest px-space-md py-2 rounded-lg shadow-sm text-on-surface outline-none focus:ring-1 focus:ring-primary disabled:opacity-60 ${
          mono ? 'font-code-base text-code-base' : 'font-body-md text-body-md'
        }`}
      />
      {hint && <span className="font-body-sm text-body-sm text-outline">{hint}</span>}
    </div>
  );
}

/** A saved-override marker, so edited fields are visible at a glance. */
function OverrideBadge() {
  const { t } = useI18n();
  return (
    <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-primary-container/30 text-primary">
      {t('pages.settings.overridden')}
    </span>
  );
}

/** A switch rendered as status only: the backend exposes no way to change it. */
function StaticSwitch({ on }: { on: boolean }) {
  return (
    <span
      aria-disabled
      className={`relative inline-flex w-9 h-5 rounded-full cursor-not-allowed ${
        on ? 'bg-primary' : 'bg-surface-container-highest'
      }`}
    >
      <span
        className={`absolute top-[2px] h-4 w-4 rounded-full bg-on-primary transition-all ${
          on ? 'left-[18px]' : 'left-[2px]'
        }`}
      />
    </span>
  );
}

/** A switch backed by a real PATCH to /api/v1/settings. */
function LiveSwitch({
  on,
  onToggle,
  disabled,
}: {
  on: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={onToggle}
      className={`relative inline-flex w-9 h-5 rounded-full transition-colors ${
        on ? 'bg-primary' : 'bg-surface-container-highest'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span
        className={`absolute top-[2px] h-4 w-4 rounded-full bg-on-primary transition-all ${
          on ? 'left-[18px]' : 'left-[2px]'
        }`}
      />
    </button>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-t border-outline-variant/20 first:border-t-0 gap-space-sm">
      <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
        {label}
      </span>
      <span className={`font-code-base text-code-base text-right truncate ${tone ?? 'text-on-surface'}`}>
        {value}
      </span>
    </div>
  );
}

interface SettingsForm {
  model: string;
  temperature: string;
  maxTokens: string;
  timeout: string;
}

function formFrom(settings: RuntimeSettings): SettingsForm {
  return {
    model: settings.model,
    temperature: String(settings.temperature),
    maxTokens: String(settings.max_tokens),
    timeout: String(settings.request_timeout_seconds),
  };
}

export default function Settings() {
  const { t, formatDateTime, formatNumber } = useI18n();
  const { data, connected, refresh } = useOverview();
  const health = useAsyncData(() => healthApi.get(), []);
  const llm = useAsyncData(() => healthApi.llm(), []);
  const runtime = useAsyncData(() => healthApi.runtime(), []);
  const settings = useAsyncData(() => settingsApi.get(), []);

  const agentId = data?.agent?.id ?? null;
  const memories = useAsyncData(
    () => (agentId ? memoryApi.listMemories(agentId) : Promise.resolve([])),
    [agentId],
  );

  const [tab, setTab] = useState<TabKey>('general');
  const [toast, setToast] = useState<{ text: string; icon: string } | null>(null);
  // Only the fields the user has actually touched. The displayed form is the
  // fetched settings overlaid with these edits, derived during render rather
  // than synced in an effect -- so a fresh fetch (after a save) is reflected
  // without a second render pass.
  const [edits, setEdits] = useState<Partial<SettingsForm>>({});
  const [saving, setSaving] = useState(false);

  const baseForm = settings.data ? formFrom(settings.data) : null;
  const form = baseForm ? { ...baseForm, ...edits } : null;

  const showToast = (text: string, icon: string) => {
    setToast({ text, icon });
    window.setTimeout(() => setToast(null), 3200);
  };

  const reloadAll = () => {
    refresh();
    health.reload();
    llm.reload();
    runtime.reload();
    memories.reload();
    settings.reload();
  };

  const backup = () => {
    const items = memories.data ?? [];
    if (items.length === 0) return;
    const blob = new Blob([items.map((item) => JSON.stringify(item)).join('\n')], {
      type: 'application/x-ndjson',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `nexus-vectors-${agentId?.slice(0, 8) ?? 'agent'}.jsonl`;
    anchor.click();
    URL.revokeObjectURL(url);
    showToast(t('pages.settings.memory.backupToast'), 'download_done');
  };

  const decision = data?.trust.default_decision ?? '--';
  const decisionLabel =
    decision === 'ASK'
      ? t('pages.settings.trust.strict')
      : decision === 'ALLOW'
        ? t('pages.settings.trust.permissive')
        : decision;

  // Editing is only offered when the override store answered. Otherwise a save
  // would reach the backend and 503, which reads as "your click did nothing".
  const canEdit = Boolean(settings.data?.storage_available) && !saving;
  const defaultOf = (key: string) => String(settings.data?.defaults[key] ?? '--');
  const isOverridden = (key: string) => Boolean(settings.data?.overridden.includes(key));

  const saveSettings = async () => {
    const current = settings.data;
    if (!current || !form) return;

    const changes: RuntimeSettingsUpdate = {};

    const model = form.model.trim();
    if (model && model !== current.model) changes.model = model;

    const temperature = Number(form.temperature);
    if (form.temperature.trim() !== '' && !Number.isNaN(temperature) && temperature !== current.temperature) {
      changes.temperature = temperature;
    }

    const maxTokens = Number(form.maxTokens);
    if (form.maxTokens.trim() !== '' && !Number.isNaN(maxTokens) && maxTokens !== current.max_tokens) {
      changes.max_tokens = Math.round(maxTokens);
    }

    const timeout = Number(form.timeout);
    if (form.timeout.trim() !== '' && !Number.isNaN(timeout) && timeout !== current.request_timeout_seconds) {
      changes.request_timeout_seconds = timeout;
    }

    if (Object.keys(changes).length === 0) {
      showToast(t('pages.settings.toasts.noChanges'), 'info');
      return;
    }

    try {
      setSaving(true);
      await settingsApi.update(changes);
      // Drop the local edits so the re-fetch's values become the baseline.
      setEdits({});
      settings.reload();
      showToast(t('pages.settings.toasts.saved'), 'save');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('pages.settings.toasts.saveFailed'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const resetSettings = async () => {
    if (!settings.data) return;
    try {
      setSaving(true);
      await settingsApi.update({
        model: null,
        temperature: null,
        max_tokens: null,
        request_timeout_seconds: null,
      });
      settings.reload();
      showToast(t('pages.settings.toasts.reset'), 'restart_alt');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('pages.settings.toasts.resetFailed'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const toggleNotifications = async () => {
    const current = settings.data;
    if (!current) return;
    const next = !current.notifications_enabled;
    try {
      setSaving(true);
      await settingsApi.update({ notifications_enabled: next });
      settings.reload();
      showToast(
        t(next ? 'pages.settings.trust.notificationsOn' : 'pages.settings.trust.notificationsOff'),
        'notifications',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('pages.settings.toasts.preferenceFailed'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const storageBanner = settings.data && !settings.data.storage_available && (
    <div className="p-space-md rounded-lg bg-error-container/20 border border-error/30 flex items-start gap-space-sm">
      <span className="material-symbols-outlined text-error text-[20px] mt-0.5">cloud_off</span>
      <div className="flex flex-col">
        <span className="font-body-md text-body-md font-medium text-on-surface">
          {t('pages.settings.storage.title')}
        </span>
        <span className="font-body-sm text-body-sm text-on-surface-variant">
          {t('pages.settings.storage.detail')}
        </span>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col w-full pb-margin">
      {/* Header */}
      <div className="relative py-space-lg flex flex-col gap-space-xs">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md">
          <div>
            <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs uppercase text-primary tracking-widest mb-1">
              <span>{t('pages.settings.eyebrow')}</span>
              <span className="text-outline">/</span>
              <span className="text-on-surface-variant">{t('pages.settings.eyebrowHost')}</span>
            </div>
            <h1 className="font-headline-lg text-headline-lg text-on-surface font-semibold tracking-tight">
              {t('pages.settings.title')}
            </h1>
            <p className="font-body-sm text-body-sm text-on-surface-variant max-w-3xl mt-0.5">
              {t('pages.settings.description')}
            </p>
          </div>
          <div className="flex items-center gap-space-sm self-start md:self-auto">
            <span className="px-space-md py-1.5 rounded-lg bg-surface-container-lowest text-outline font-label-mono-xs text-label-mono-xs flex items-center gap-1.5">
              <span className="material-symbols-outlined text-[16px]">
                {settings.data?.storage_available ? 'tune' : 'lock'}
              </span>
              {t(
                settings.data?.storage_available
                  ? 'pages.settings.editable'
                  : 'pages.settings.readOnly',
              )}
            </span>
            <button
              type="button"
              onClick={() => {
                reloadAll();
                showToast(t('pages.settings.reloaded'), 'refresh');
              }}
              className="px-space-md py-1.5 rounded-lg bg-surface-container text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors font-body-sm text-body-sm flex items-center gap-1.5 shadow-sm"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
              <span>{t('common.reload')}</span>
            </button>
          </div>
        </div>

        {/* Sub-navigation */}
        <div className="mt-space-md flex items-center gap-space-xs overflow-x-auto pb-1">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              className={`px-space-md py-2 rounded-lg font-body-sm text-body-sm whitespace-nowrap transition-colors flex items-center gap-1.5 ${
                tab === item.key
                  ? 'bg-surface-container-high text-on-surface font-medium shadow-sm'
                  : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
            >
              {tab === item.key ? (
                <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
              ) : (
                <span className="material-symbols-outlined text-[16px]">{item.icon}</span>
              )}
              <span>{t(item.labelKey)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-gutter mt-space-sm">
        <div className="xl:col-span-8 flex flex-col gap-gutter">
          {(tab === 'general' || tab === 'runtime') && (
            <SectionCard
              icon="lan"
              iconTone="text-primary"
              title={t('pages.settings.connection.title')}
              subtitle={t('pages.settings.connection.subtitle')}
              badge={
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-container-lowest font-label-mono-xs text-label-mono-xs ${
                    connected ? 'text-tertiary' : 'text-error'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-tertiary animate-pulse' : 'bg-error'}`} />
                  <span>
                    {t(
                      connected
                        ? 'pages.settings.connection.reachable'
                        : 'pages.settings.connection.unreachable',
                    )}
                  </span>
                </div>
              }
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
                <div className="flex flex-col gap-1.5">
                  <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                    {t('pages.settings.connection.endpoint')}
                  </label>
                  <ReadOnlyValue
                    mono
                    value={
                      <>
                        <span className="material-symbols-outlined text-[16px] text-outline">dns</span>
                        <span className="w-full">{API_BASE_URL}</span>
                        <a
                          href={`${API_BASE_URL}/docs`}
                          target="_blank"
                          rel="noreferrer"
                          className="font-label-mono-xs text-label-mono-xs text-primary hover:underline whitespace-nowrap"
                        >
                          /docs
                        </a>
                      </>
                    }
                  />
                  <span className="font-body-sm text-body-sm text-outline">
                    {t('pages.settings.connection.routesHint')}
                    <span className="font-code-base">/api/v1/…</span>
                    {t('pages.settings.connection.routesHintAfter')}
                  </span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                    {t('pages.settings.connection.environment')}
                  </label>
                  <ReadOnlyValue
                    value={<span className="w-full">{data?.system.environment ?? '--'}</span>}
                  />
                  <span className="font-body-sm text-body-sm text-outline">
                    {t('pages.settings.connection.environmentHint', {
                      phase: health.data?.phase ?? '--',
                      service: health.data?.service ?? '--',
                    })}
                  </span>
                </div>
              </div>

              <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-space-md shadow-sm">
                <div className="flex items-center gap-space-md">
                  <div className="w-7 h-7 rounded bg-surface-container-high flex items-center justify-center">
                    <span className="material-symbols-outlined text-[16px] text-secondary">sync_alt</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      {t('pages.settings.connection.restTitle')}
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      {t('pages.settings.connection.restDetail')}
                    </span>
                  </div>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-1 rounded bg-surface-container-highest text-on-surface">
                  {t('pages.settings.connection.noSse')}
                </span>
              </div>
            </SectionCard>
          )}

          {(tab === 'general' || tab === 'model') && (
            <SectionCard
              icon="neurology"
              title={t('pages.settings.model.title')}
              subtitle={t('pages.settings.model.subtitle')}
              badge={
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-container-lowest font-label-mono-xs text-label-mono-xs ${
                    data?.model.configured ? 'text-tertiary' : 'text-error'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${data?.model.configured ? 'bg-tertiary animate-pulse' : 'bg-error'}`} />
                  <span>
                    {t(
                      data?.model.configured
                        ? 'pages.settings.model.credentialsOk'
                        : 'pages.settings.model.noCredentials',
                    )}
                  </span>
                </div>
              }
            >
              {settings.loading && !settings.data ? (
                <LoadingRow label={t('pages.settings.model.loading')} />
              ) : settings.error ? (
                <ErrorRow message={settings.error} onRetry={settings.reload} />
              ) : (
                <>
                  {storageBanner}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
                    <TextField
                      label={t('pages.settings.model.active')}
                      value={form?.model ?? ''}
                      onChange={(value) => setEdits((prev) => ({ ...prev, model: value }))}
                      disabled={!canEdit}
                      mono
                      badge={isOverridden('model') ? <OverrideBadge /> : null}
                      hint={
                        <>
                          {t('pages.settings.model.environmentDefault')}
                          <span className="font-code-base">{defaultOf('model')}</span>
                        </>
                      }
                    />
                    <div className="flex flex-col gap-1.5">
                      <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                        {t('pages.settings.model.provider')}
                      </label>
                      <ReadOnlyValue
                        value={
                          <>
                            <span className="material-symbols-outlined text-[16px] text-secondary">cloud</span>
                            <span className="w-full">{settings.data?.provider.name ?? data?.model.provider ?? '--'}</span>
                          </>
                        }
                      />
                      <span className="font-body-sm text-body-sm text-outline">
                        {t('pages.settings.model.providerStatus', {
                          apiKey: t(
                            settings.data?.provider.api_key_configured
                              ? 'pages.settings.model.configured'
                              : 'pages.settings.model.absent',
                          ),
                          baseUrl: t(
                            settings.data?.provider.base_url_configured
                              ? 'pages.settings.model.configured'
                              : 'pages.settings.model.absent',
                          ),
                        })}
                      </span>
                    </div>
                  </div>

                  <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col gap-space-md shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-space-sm">
                      <div className="flex items-center gap-2">
                        <span className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface font-semibold">
                          {t('pages.settings.model.generation')}
                        </span>
                        <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-highest text-outline">
                          {t('pages.settings.model.hotApplied')}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={resetSettings}
                          disabled={!canEdit}
                          className="px-space-md py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-bright disabled:opacity-50 text-on-surface font-body-sm text-body-sm transition-colors flex items-center gap-1"
                        >
                          <span className="material-symbols-outlined text-[15px]">restart_alt</span>
                          <span>{t('pages.settings.model.resetEnvironment')}</span>
                        </button>
                        <button
                          type="button"
                          onClick={saveSettings}
                          disabled={!canEdit}
                          className="px-space-md py-1.5 rounded-lg bg-primary text-on-primary hover:brightness-110 disabled:opacity-50 font-body-sm text-body-sm font-medium transition-colors flex items-center gap-1"
                        >
                          <span className="material-symbols-outlined text-[15px]">
                            {saving ? 'progress_activity' : 'save'}
                          </span>
                          <span>{t(saving ? 'common.saving' : 'common.save')}</span>
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-space-md">
                      <TextField
                        label={t('pages.settings.model.temperature')}
                        type="number"
                        min={0}
                        max={2}
                        step={0.1}
                        value={form?.temperature ?? ''}
                        onChange={(value) => setEdits((prev) => ({ ...prev, temperature: value }))}
                        disabled={!canEdit}
                        badge={isOverridden('temperature') ? <OverrideBadge /> : null}
                        hint={
                          <>
                            {t('pages.settings.model.defaultHint', { value: defaultOf('temperature') })}
                          </>
                        }
                      />
                      <TextField
                        label={t('pages.settings.model.maxTokens')}
                        type="number"
                        min={1}
                        max={32768}
                        step={1}
                        value={form?.maxTokens ?? ''}
                        onChange={(value) => setEdits((prev) => ({ ...prev, maxTokens: value }))}
                        disabled={!canEdit}
                        badge={isOverridden('max_tokens') ? <OverrideBadge /> : null}
                        hint={
                          <>
                            {t('pages.settings.model.defaultHint', { value: defaultOf('max_tokens') })}
                          </>
                        }
                      />
                      <TextField
                        label={t('pages.settings.model.timeout')}
                        type="number"
                        min={1}
                        max={600}
                        step={1}
                        value={form?.timeout ?? ''}
                        onChange={(value) => setEdits((prev) => ({ ...prev, timeout: value }))}
                        disabled={!canEdit}
                        badge={isOverridden('request_timeout_seconds') ? <OverrideBadge /> : null}
                        hint={
                          <>
                            {t('pages.settings.model.defaultHint', {
                              value: defaultOf('request_timeout_seconds'),
                            })}
                          </>
                        }
                      />
                    </div>

                    <span className="font-body-sm text-body-sm text-outline">
                      {t('pages.settings.model.overridesNote')}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-space-sm pt-space-xs">
                    <div className="bg-surface-container-lowest p-space-md rounded-lg flex flex-col gap-1 shadow-sm">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                        {t('pages.settings.model.statModel')}
                      </span>
                      <span className="font-headline-sm text-headline-sm font-semibold text-on-surface truncate">
                        {settings.data?.model ?? data?.model.model ?? '--'}
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant truncate">
                        {data?.model.provider ?? '--'}
                      </span>
                    </div>
                    <div className="bg-surface-container-lowest p-space-md rounded-lg flex flex-col gap-1 shadow-sm">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                        {t('pages.settings.model.statConfigured')}
                      </span>
                      <span className={`font-headline-sm text-headline-sm font-semibold ${data?.model.configured ? 'text-tertiary' : 'text-error'}`}>
                        {t(data?.model.configured ? 'common.yes' : 'common.no')}
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant">
                        {t('pages.settings.model.statCredentials')}
                      </span>
                    </div>
                    <div className="bg-surface-container-lowest p-space-md rounded-lg flex flex-col gap-1 shadow-sm">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                        {t('pages.settings.model.statUptime')}
                      </span>
                      <span className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                        {formatUptime(data?.system.uptime_seconds)}
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant">
                        {t('pages.settings.model.statBackend')}
                      </span>
                    </div>
                  </div>
                </>
              )}
            </SectionCard>
          )}

          {(tab === 'general' || tab === 'memory') && (
            <SectionCard
              icon="database"
              title={t('pages.settings.memory.title')}
              subtitle={t('pages.settings.memory.subtitle')}
            >
              <div className="flex flex-col gap-space-sm">
                <div className="p-space-md rounded-lg bg-surface-container-lowest flex items-center justify-between shadow-sm">
                  <div className="flex flex-col">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      {t('pages.settings.memory.vectorStore')}
                    </span>
                    <span className="font-label-mono-xs text-label-mono-xs text-tertiary">
                      {memories.loading
                        ? t('pages.settings.memory.querying')
                        : t('pages.settings.memory.loaded', {
                            count: formatNumber(memories.data?.length ?? 0),
                          })}
                    </span>
                  </div>
                  <button
                    type="button"
                    disabled={(memories.data?.length ?? 0) === 0}
                    onClick={backup}
                    className="px-space-md py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-bright disabled:opacity-50 text-on-surface font-body-sm text-body-sm transition-colors flex items-center gap-1"
                  >
                    <span className="material-symbols-outlined text-[15px]">download</span>
                    <span>{t('pages.settings.memory.backup')}</span>
                  </button>
                </div>

                <div className="p-space-md rounded-lg bg-surface-container-lowest flex items-center justify-between shadow-sm">
                  <div className="flex flex-col">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      {t('pages.settings.memory.purge')}
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      {t('pages.settings.memory.purgeDetail')}
                    </span>
                  </div>
                  <button
                    type="button"
                    disabled
                    className="px-space-md py-1.5 rounded-lg bg-surface-container-high text-outline font-body-sm text-body-sm cursor-not-allowed flex items-center gap-1"
                  >
                    <span className="material-symbols-outlined text-[15px]">cleaning_services</span>
                    <span>{t('common.unavailable')}</span>
                  </button>
                </div>
              </div>
            </SectionCard>
          )}
        </div>

        <div className="xl:col-span-4 flex flex-col gap-gutter">
          {(tab === 'general' || tab === 'runtime') && (
            <SectionCard
              icon="deployed_code"
              title={t('pages.settings.runtime.title')}
              subtitle={t('pages.settings.runtime.subtitle')}
              badge={
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-container-lowest font-label-mono-xs text-label-mono-xs ${
                    runtime.data?.available ? 'text-tertiary' : 'text-error'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${runtime.data?.available ? 'bg-tertiary' : 'bg-error'}`} />
                  <span>
                    {t(
                      runtime.data?.available
                        ? 'pages.settings.runtime.available'
                        : 'pages.settings.runtime.unavailable',
                    )}
                  </span>
                </div>
              }
            >
              {runtime.loading ? (
                <LoadingRow label={t('pages.settings.runtime.loading')} />
              ) : runtime.error ? (
                <ErrorRow message={runtime.error} onRetry={runtime.reload} />
              ) : (
                <div className="flex flex-col">
                  <Row label={t('pages.settings.runtime.provider')} value={runtime.data?.provider ?? '--'} />
                  <Row
                    label={t('pages.settings.runtime.availability')}
                    value={t(runtime.data?.available ? 'common.yes' : 'common.no')}
                    tone={runtime.data?.available ? 'text-tertiary' : 'text-error'}
                  />
                  <Row label={t('pages.settings.runtime.version')} value={runtime.data?.version ?? '--'} />
                  <Row
                    label={t('pages.settings.runtime.detail')}
                    value={runtime.data?.detail || t('pages.settings.runtime.noDetail')}
                  />
                </div>
              )}
            </SectionCard>
          )}

          {(tab === 'general' || tab === 'trust') && (
            <SectionCard
              icon="security"
              iconTone="text-tertiary"
              title={t('pages.settings.trust.title')}
              subtitle={t('pages.settings.trust.subtitle')}
            >
              <div className="flex flex-col gap-space-sm">
                <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                  {t('pages.settings.trust.defaultDecision')}
                </label>
                <div className="flex items-start gap-space-sm p-space-md rounded-lg bg-surface-container-high">
                  <span className="material-symbols-outlined text-tertiary text-[20px] mt-0.5">shield</span>
                  <div className="flex flex-col">
                    <div className="flex items-center gap-space-xs">
                      <span className="font-body-md text-body-md font-semibold text-on-surface">
                        {decisionLabel}
                      </span>
                      <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-tertiary-container/30 text-tertiary">
                        {t('pages.settings.trust.current')}
                      </span>
                    </div>
                    <p className="font-body-sm text-body-sm text-outline mt-0.5">
                      {t('pages.settings.trust.decisionNote')}
                    </p>
                  </div>
                </div>

                <div className="flex flex-col">
                  <Row
                    label={t('pages.settings.trust.allowGrants')}
                    value={formatNumber(data?.trust.allow_grants ?? 0)}
                    tone="text-tertiary"
                  />
                  <Row
                    label={t('pages.settings.trust.askGrants')}
                    value={formatNumber(data?.trust.ask_grants ?? 0)}
                    tone="text-primary"
                  />
                  <Row
                    label={t('pages.settings.trust.denyGrants')}
                    value={formatNumber(data?.trust.deny_grants ?? 0)}
                    tone="text-error"
                  />
                  <Row label={t('pages.settings.trust.total')} value={formatNumber(data?.trust.total_grants ?? 0)} />
                </div>
              </div>

              <div className="flex flex-col gap-space-md pt-space-xs">
                <div className="flex items-center justify-between p-space-md rounded-lg bg-surface-container-lowest shadow-sm">
                  <div className="flex flex-col pr-2">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      {t('pages.settings.trust.firewall')}
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      {t('pages.settings.trust.firewallNote')}
                    </span>
                  </div>
                  <StaticSwitch on={settings.data?.memory_firewall_enforced ?? true} />
                </div>
                <div className="flex items-center justify-between p-space-md rounded-lg bg-surface-container-lowest shadow-sm">
                  <div className="flex flex-col pr-2">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      {t('pages.settings.trust.notifications')}
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      {t('pages.settings.trust.notificationsNote')}
                    </span>
                  </div>
                  <LiveSwitch
                    on={settings.data?.notifications_enabled ?? false}
                    onToggle={toggleNotifications}
                    disabled={!canEdit}
                  />
                </div>
              </div>
            </SectionCard>
          )}

          {(tab === 'general' || tab === 'about') && (
            <SectionCard
              icon="info"
              title={t('pages.settings.about.title')}
              subtitle={t('pages.settings.about.subtitle')}
            >
              <div className="flex flex-col">
                <Row label={t('pages.settings.about.service')} value={health.data?.service ?? '--'} />
                <Row
                  label={t('common.status')}
                  value={health.data?.status ?? '--'}
                  tone={connected ? 'text-tertiary' : 'text-error'}
                />
                <Row label={t('pages.settings.about.phase')} value={health.data?.phase ?? '--'} />
                <Row
                  label={t('pages.settings.about.database')}
                  value={health.data?.database ?? data?.system.database ?? '--'}
                />
                <Row label={t('pages.settings.about.environment')} value={data?.system.environment ?? '--'} />
                <Row
                  label={t('pages.settings.about.uptime')}
                  value={formatUptime(data?.system.uptime_seconds)}
                  tone="text-tertiary"
                />
                <Row
                  label={t('pages.settings.about.saved')}
                  value={formatDateTime(
                    settings.data?.updated_at,
                    t('pages.settings.about.noChanges'),
                  )}
                />
              </div>
              <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
                {t('pages.settings.about.note')}
              </p>
            </SectionCard>
          )}
        </div>
      </div>

      {/* Toast for real actions only */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-surface-container-highest text-on-surface px-space-lg py-space-md rounded-lg shadow-xl flex items-center gap-space-sm">
          <span className="material-symbols-outlined text-tertiary text-[20px]">{toast.icon}</span>
          <span className="font-body-md text-body-md">{toast.text}</span>
        </div>
      )}
    </div>
  );
}
