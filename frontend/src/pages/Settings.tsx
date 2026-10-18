import { useState, type ReactNode } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { useOverview } from '../hooks/useOverview';
import { healthApi } from '../services/api/healthApi';
import { memoryApi } from '../services/api/memoryApi';
import { settingsApi } from '../services/api/settingsApi';
import { API_BASE_URL } from '../services/api/apiClient';
import { ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { RuntimeSettings, RuntimeSettingsUpdate } from '../types';

type TabKey = 'general' | 'model' | 'memory' | 'runtime' | 'trust' | 'about';

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: 'general', label: 'General', icon: 'tune' },
  { key: 'model', label: 'Modelo & Inferencia', icon: 'neurology' },
  { key: 'memory', label: 'Memoria & Privacidad', icon: 'memory' },
  { key: 'runtime', label: 'Entorno & Runtime', icon: 'deployed_code' },
  { key: 'trust', label: 'Seguridad & Confianza', icon: 'shield' },
  { key: 'about', label: 'Acerca de NEXUS', icon: 'info' },
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
  return (
    <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-primary-container/30 text-primary">
      MODIFICADO
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
    showToast('Descargando snapshot de vectores (.jsonl)', 'download_done');
  };

  const decision = data?.trust.default_decision ?? '--';
  const decisionLabel =
    decision === 'ASK' ? 'ESTRICTO (Zero-Trust ASK)' : decision === 'ALLOW' ? 'PERMISIVO' : decision;

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
      showToast('No hay cambios que guardar.', 'info');
      return;
    }

    try {
      setSaving(true);
      await settingsApi.update(changes);
      // Drop the local edits so the re-fetch's values become the baseline.
      setEdits({});
      settings.reload();
      showToast('Ajustes guardados y aplicados al runtime.', 'save');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'No se pudieron guardar los ajustes.', 'error');
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
      showToast('Ajustes restablecidos a los valores del entorno.', 'restart_alt');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'No se pudieron restablecer los ajustes.', 'error');
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
      showToast(`Notificaciones ${next ? 'activadas' : 'desactivadas'}.`, 'notifications');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'No se pudo cambiar la preferencia.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const storageBanner = settings.data && !settings.data.storage_available && (
    <div className="p-space-md rounded-lg bg-error-container/20 border border-error/30 flex items-start gap-space-sm">
      <span className="material-symbols-outlined text-error text-[20px] mt-0.5">cloud_off</span>
      <div className="flex flex-col">
        <span className="font-body-md text-body-md font-medium text-on-surface">
          Almacén de ajustes no disponible
        </span>
        <span className="font-body-sm text-body-sm text-on-surface-variant">
          El backend no pudo leer la tabla de ajustes, así que se muestran los valores del entorno.
          No se pueden guardar cambios hasta que el almacén responda.
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
              <span>SYS_CONFIG // KERNEL_CTL</span>
              <span className="text-outline">/</span>
              <span className="text-on-surface-variant">HOST_LOCAL</span>
            </div>
            <h1 className="font-headline-lg text-headline-lg text-on-surface font-semibold tracking-tight">
              Configuración del Sistema
            </h1>
            <p className="font-body-sm text-body-sm text-on-surface-variant max-w-3xl mt-0.5">
              Estado en vivo de modelos, memoria, entorno de ejecución y postura del Trust Engine.
            </p>
          </div>
          <div className="flex items-center gap-space-sm self-start md:self-auto">
            <span className="px-space-md py-1.5 rounded-lg bg-surface-container-lowest text-outline font-label-mono-xs text-label-mono-xs flex items-center gap-1.5">
              <span className="material-symbols-outlined text-[16px]">
                {settings.data?.storage_available ? 'tune' : 'lock'}
              </span>
              {settings.data?.storage_available ? 'PARÁMETROS EDITABLES' : 'SOLO LECTURA'}
            </span>
            <button
              type="button"
              onClick={() => {
                reloadAll();
                showToast('Estado recargado desde el backend.', 'refresh');
              }}
              className="px-space-md py-1.5 rounded-lg bg-surface-container text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors font-body-sm text-body-sm flex items-center gap-1.5 shadow-sm"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
              <span>Recargar</span>
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
              <span>{item.label}</span>
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
              title="Conexión con el Backend"
              subtitle="FastAPI Core Runtime y parámetros de conexión del cliente."
              badge={
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-container-lowest font-label-mono-xs text-label-mono-xs ${
                    connected ? 'text-tertiary' : 'text-error'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-tertiary animate-pulse' : 'bg-error'}`} />
                  <span>{connected ? 'BACKEND ALCANZABLE' : 'BACKEND INALCANZABLE'}</span>
                </div>
              }
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
                <div className="flex flex-col gap-1.5">
                  <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                    Endpoint Base del Cliente
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
                    El cliente añade las rutas (<span className="font-code-base">/api/v1/…</span>) sobre esta base.
                  </span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                    Entorno del Servidor
                  </label>
                  <ReadOnlyValue
                    value={<span className="w-full">{data?.system.environment ?? '--'}</span>}
                  />
                  <span className="font-body-sm text-body-sm text-outline">
                    Fase: {health.data?.phase ?? '--'} · Servicio: {health.data?.service ?? '--'}
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
                      Comunicación REST (JSON)
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      El backend no expone streaming SSE ni tokens incremental.
                    </span>
                  </div>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-1 rounded bg-surface-container-highest text-on-surface">
                  SIN SSE
                </span>
              </div>
            </SectionCard>
          )}

          {(tab === 'general' || tab === 'model') && (
            <SectionCard
              icon="neurology"
              title="Proveedor de Modelo & Inferencia"
              subtitle="Modelo fundacional y parámetros de generación aplicados en caliente."
              badge={
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-container-lowest font-label-mono-xs text-label-mono-xs ${
                    data?.model.configured ? 'text-tertiary' : 'text-error'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${data?.model.configured ? 'bg-tertiary animate-pulse' : 'bg-error'}`} />
                  <span>{data?.model.configured ? 'CREDENCIALES OK' : 'SIN CREDENCIALES'}</span>
                </div>
              }
            >
              {settings.loading && !settings.data ? (
                <LoadingRow label="Consultando ajustes…" />
              ) : settings.error ? (
                <ErrorRow message={settings.error} onRetry={settings.reload} />
              ) : (
                <>
                  {storageBanner}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
                    <TextField
                      label="Modelo Activo"
                      value={form?.model ?? ''}
                      onChange={(value) => setEdits((prev) => ({ ...prev, model: value }))}
                      disabled={!canEdit}
                      mono
                      badge={isOverridden('model') ? <OverrideBadge /> : null}
                      hint={<>Predeterminado del entorno: <span className="font-code-base">{defaultOf('model')}</span></>}
                    />
                    <div className="flex flex-col gap-1.5">
                      <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                        Proveedor de Inferencia
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
                        Clave API: {settings.data?.provider.api_key_configured ? 'configurada' : 'ausente'} · Base URL:{' '}
                        {settings.data?.provider.base_url_configured ? 'configurada' : 'ausente'}. No editables desde el panel.
                      </span>
                    </div>
                  </div>

                  <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col gap-space-md shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-space-sm">
                      <div className="flex items-center gap-2">
                        <span className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface font-semibold">
                          Parámetros de Generación
                        </span>
                        <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-highest text-outline">
                          APLICADOS EN CALIENTE
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
                          <span>Restablecer entorno</span>
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
                          <span>{saving ? 'Guardando…' : 'Guardar'}</span>
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-space-md">
                      <TextField
                        label="Temperatura"
                        type="number"
                        min={0}
                        max={2}
                        step={0.1}
                        value={form?.temperature ?? ''}
                        onChange={(value) => setEdits((prev) => ({ ...prev, temperature: value }))}
                        disabled={!canEdit}
                        badge={isOverridden('temperature') ? <OverrideBadge /> : null}
                        hint={<>Predeterminado: {defaultOf('temperature')}</>}
                      />
                      <TextField
                        label="Máx. Tokens"
                        type="number"
                        min={1}
                        max={32768}
                        step={1}
                        value={form?.maxTokens ?? ''}
                        onChange={(value) => setEdits((prev) => ({ ...prev, maxTokens: value }))}
                        disabled={!canEdit}
                        badge={isOverridden('max_tokens') ? <OverrideBadge /> : null}
                        hint={<>Predeterminado: {defaultOf('max_tokens')}</>}
                      />
                      <TextField
                        label="Timeout (s)"
                        type="number"
                        min={1}
                        max={600}
                        step={1}
                        value={form?.timeout ?? ''}
                        onChange={(value) => setEdits((prev) => ({ ...prev, timeout: value }))}
                        disabled={!canEdit}
                        badge={isOverridden('request_timeout_seconds') ? <OverrideBadge /> : null}
                        hint={<>Predeterminado: {defaultOf('request_timeout_seconds')}</>}
                      />
                    </div>

                    <span className="font-body-sm text-body-sm text-outline">
                      Los valores modificados se guardan en el backend y sustituyen al entorno en la siguiente llamada
                      al modelo. No hay listado de modelos disponibles: el identificador se escribe en texto.
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-space-sm pt-space-xs">
                    <div className="bg-surface-container-lowest p-space-md rounded-lg flex flex-col gap-1 shadow-sm">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">Modelo</span>
                      <span className="font-headline-sm text-headline-sm font-semibold text-on-surface truncate">
                        {settings.data?.model ?? data?.model.model ?? '--'}
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant truncate">
                        {data?.model.provider ?? '--'}
                      </span>
                    </div>
                    <div className="bg-surface-container-lowest p-space-md rounded-lg flex flex-col gap-1 shadow-sm">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">Configurado</span>
                      <span className={`font-headline-sm text-headline-sm font-semibold ${data?.model.configured ? 'text-tertiary' : 'text-error'}`}>
                        {data?.model.configured ? 'SÍ' : 'NO'}
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant">Credenciales del proveedor</span>
                    </div>
                    <div className="bg-surface-container-lowest p-space-md rounded-lg flex flex-col gap-1 shadow-sm">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">Uptime</span>
                      <span className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                        {formatUptime(data?.system.uptime_seconds)}
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant">Servicio backend</span>
                    </div>
                  </div>
                </>
              )}
            </SectionCard>
          )}

          {(tab === 'general' || tab === 'memory') && (
            <SectionCard
              icon="database"
              title="Memoria & Privacidad"
              subtitle="Almacenamiento vectorial y datos persistentes del agente."
            >
              <div className="flex flex-col gap-space-sm">
                <div className="p-space-md rounded-lg bg-surface-container-lowest flex items-center justify-between shadow-sm">
                  <div className="flex flex-col">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      Base de Memoria Vectorial
                    </span>
                    <span className="font-label-mono-xs text-label-mono-xs text-tertiary">
                      {memories.loading
                        ? 'Consultando…'
                        : `${memories.data?.length ?? 0} recuerdos cargados · pgvector`}
                    </span>
                  </div>
                  <button
                    type="button"
                    disabled={(memories.data?.length ?? 0) === 0}
                    onClick={backup}
                    className="px-space-md py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-bright disabled:opacity-50 text-on-surface font-body-sm text-body-sm transition-colors flex items-center gap-1"
                  >
                    <span className="material-symbols-outlined text-[15px]">download</span>
                    <span>Backup (.jsonl)</span>
                  </button>
                </div>

                <div className="p-space-md rounded-lg bg-surface-container-lowest flex items-center justify-between shadow-sm">
                  <div className="flex flex-col">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      Purgar Caché Local
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      No existe un endpoint de purga de caché en el backend.
                    </span>
                  </div>
                  <button
                    type="button"
                    disabled
                    className="px-space-md py-1.5 rounded-lg bg-surface-container-high text-outline font-body-sm text-body-sm cursor-not-allowed flex items-center gap-1"
                  >
                    <span className="material-symbols-outlined text-[15px]">cleaning_services</span>
                    <span>No disponible</span>
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
              title="Entorno & Runtime"
              subtitle="Sandbox de ejecución de herramientas."
              badge={
                <div
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-container-lowest font-label-mono-xs text-label-mono-xs ${
                    runtime.data?.available ? 'text-tertiary' : 'text-error'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${runtime.data?.available ? 'bg-tertiary' : 'bg-error'}`} />
                  <span>{runtime.data?.available ? 'DISPONIBLE' : 'NO DISPONIBLE'}</span>
                </div>
              }
            >
              {runtime.loading ? (
                <LoadingRow label="Consultando runtime…" />
              ) : runtime.error ? (
                <ErrorRow message={runtime.error} onRetry={runtime.reload} />
              ) : (
                <div className="flex flex-col">
                  <Row label="Provider" value={runtime.data?.provider ?? '--'} />
                  <Row
                    label="Disponible"
                    value={runtime.data?.available ? 'SÍ' : 'NO'}
                    tone={runtime.data?.available ? 'text-tertiary' : 'text-error'}
                  />
                  <Row label="Versión" value={runtime.data?.version ?? '--'} />
                  <Row label="Detalle" value={runtime.data?.detail || 'sin detalle'} />
                </div>
              )}
            </SectionCard>
          )}

          {(tab === 'general' || tab === 'trust') && (
            <SectionCard
              icon="security"
              iconTone="text-tertiary"
              title="Trust Engine"
              subtitle="Políticas de aislamiento y permisos."
            >
              <div className="flex flex-col gap-space-sm">
                <label className="font-label-mono-xs text-label-mono-xs uppercase text-on-surface-variant font-medium">
                  Decisión por Defecto (servidor)
                </label>
                <div className="flex items-start gap-space-sm p-space-md rounded-lg bg-surface-container-high">
                  <span className="material-symbols-outlined text-tertiary text-[20px] mt-0.5">shield</span>
                  <div className="flex flex-col">
                    <div className="flex items-center gap-space-xs">
                      <span className="font-body-md text-body-md font-semibold text-on-surface">
                        {decisionLabel}
                      </span>
                      <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-tertiary-container/30 text-tertiary">
                        ACTUAL
                      </span>
                    </div>
                    <p className="font-body-sm text-body-sm text-outline mt-0.5">
                      Modo reportado por el backend y deliberadamente no editable: ALLOW convertiría al Trust Engine
                      en un sello ciego. Se configura en el entorno del servidor.
                    </p>
                  </div>
                </div>

                <div className="flex flex-col">
                  <Row label="Concesiones ALLOW" value={String(data?.trust.allow_grants ?? 0)} tone="text-tertiary" />
                  <Row label="Concesiones ASK" value={String(data?.trust.ask_grants ?? 0)} tone="text-primary" />
                  <Row label="Concesiones DENY" value={String(data?.trust.deny_grants ?? 0)} tone="text-error" />
                  <Row label="Total" value={String(data?.trust.total_grants ?? 0)} />
                </div>
              </div>

              <div className="flex flex-col gap-space-md pt-space-xs">
                <div className="flex items-center justify-between p-space-md rounded-lg bg-surface-container-lowest shadow-sm">
                  <div className="flex flex-col pr-2">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      Memory Sanitization Firewall
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      Refusa secretos e instrucciones al persistir. Forzado en el backend: no se puede desactivar
                      desde el panel.
                    </span>
                  </div>
                  <StaticSwitch on={settings.data?.memory_firewall_enforced ?? true} />
                </div>
                <div className="flex items-center justify-between p-space-md rounded-lg bg-surface-container-lowest shadow-sm">
                  <div className="flex flex-col pr-2">
                    <span className="font-body-md text-body-md font-medium text-on-surface">
                      Notificaciones de Aprobación
                    </span>
                    <span className="font-body-sm text-body-sm text-outline">
                      Preferencia guardada en el backend. Aún no envía avisos; solo recuerda la elección.
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
              title="Acerca de NEXUS"
              subtitle="Identidad y diagnóstico del servicio."
            >
              <div className="flex flex-col">
                <Row label="Servicio" value={health.data?.service ?? '--'} />
                <Row label="Estado" value={health.data?.status ?? '--'} tone={connected ? 'text-tertiary' : 'text-error'} />
                <Row label="Fase" value={health.data?.phase ?? '--'} />
                <Row label="Database" value={health.data?.database ?? data?.system.database ?? '--'} />
                <Row label="Entorno" value={data?.system.environment ?? '--'} />
                <Row label="Uptime" value={formatUptime(data?.system.uptime_seconds)} tone="text-tertiary" />
                <Row label="Ajustes guardados" value={settings.data?.updated_at ?? 'sin cambios'} />
              </div>
              <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
                Editable desde el panel: modelo, temperatura, máx. tokens, timeout y notificaciones. No editable:
                clave API, base URL, trust y firewall de memoria, que se fijan en el entorno del servidor.
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
