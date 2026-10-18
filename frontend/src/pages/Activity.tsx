import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { activityApi } from '../services/api/activityApi';
import { permissionsApi } from '../services/api/permissionsApi';
import { ApiError } from '../services/api/apiClient';
import { EmptyRow, ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { ActivityCategoryCount, ActivityEvent, ActivityWindow } from '../types';

/** How often the feed re-reads the backend while "live" is on. */
const POLL_INTERVAL_MS = 15_000;

const WINDOWS: { value: ActivityWindow; label: string }[] = [
  { value: 'today', label: 'Hoy' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: 'all', label: 'Todo' },
];

const STATUSES: { value: string; label: string }[] = [
  { value: 'ALL', label: 'Todos los estados' },
  { value: 'SUCCESS', label: 'Éxito (ALLOW / SUCCESS)' },
  { value: 'PENDING', label: 'Pendiente (ASK / WAITING)' },
  { value: 'DENIED', label: 'Bloqueado (DENY / HALT)' },
  { value: 'ERROR', label: 'Errores' },
];

const CATEGORY_ICON: Record<string, string> = {
  TOOL: 'build_circle',
  TRUST: 'verified_user',
  MEMORY: 'data_object',
  RUN: 'play_circle',
  SYSTEM: 'settings',
};

const CATEGORY_COLOR: Record<string, string> = {
  TOOL: 'bg-secondary-fixed-dim',
  TRUST: 'bg-tertiary',
  MEMORY: 'bg-primary',
  RUN: 'bg-secondary',
  SYSTEM: 'bg-surface-container-highest',
};

interface OutcomeStyle {
  badge: string;
  dot: string;
  text: string;
}

function outcomeStyle(outcome: string): OutcomeStyle {
  switch (outcome) {
    case 'SUCCESS':
      return { badge: 'bg-tertiary-container/20 text-tertiary', dot: 'bg-tertiary', text: 'text-tertiary' };
    case 'DENIED':
    case 'ERROR':
      return { badge: 'bg-error-container/30 text-error', dot: 'bg-error', text: 'text-error' };
    case 'PENDING':
      return { badge: 'bg-secondary-container/20 text-secondary', dot: 'bg-secondary animate-pulse', text: 'text-secondary' };
    default:
      return {
        badge: 'bg-surface-container-high text-on-surface-variant',
        dot: 'bg-outline',
        text: 'text-on-surface-variant',
      };
  }
}

function riskClass(risk: string): string {
  if (risk === 'HIGH') return 'text-error';
  if (risk === 'MEDIUM') return 'text-primary';
  return 'text-tertiary';
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '--:--:--' : date.toLocaleTimeString([], { hour12: false });
}

function formatStamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour12: false })}`;
}

/** A short, stable display id derived from the event's own key. */
function shortRef(id: string): string {
  const tail = id.includes(':') ? id.slice(id.indexOf(':') + 1) : id;
  return `#${tail.replace(/-/g, '').slice(0, 6).toUpperCase()}`;
}

function permissionIdOf(id: string): string | null {
  return id.startsWith('permission:') ? id.slice('permission:'.length) : null;
}

function download(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function toCsv(events: ActivityEvent[]): string {
  const header = [
    'timestamp',
    'category',
    'kind',
    'outcome',
    'title',
    'source',
    'reference',
    'agent_run_id',
    'detail',
  ];
  const escape = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const rows = events.map((event) =>
    [
      event.timestamp,
      event.category,
      event.kind,
      event.outcome,
      event.title,
      event.source,
      event.reference,
      event.agent_run_id,
      event.detail,
    ]
      .map(escape)
      .join(','),
  );
  return [header.join(','), ...rows].join('\n');
}

function Sparkline({ values, peak }: { values: number[]; peak: number }) {
  const width = 200;
  const height = 40;
  if (values.length === 0) {
    return <div className="h-12 flex items-center justify-center font-label-mono-xs text-label-mono-xs text-outline">Sin eventos en la ventana</div>;
  }
  const max = Math.max(1, peak);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => {
    const x = index * step;
    const y = height - (value / max) * (height - 4) - 2;
    return [x, y] as const;
  });
  const line = points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${width},${height} L0,${height} Z`;
  return (
    <svg className="w-full h-12 text-primary overflow-visible" preserveAspectRatio="none" viewBox={`0 0 ${width} ${height}`}>
      <defs>
        <linearGradient id="activity-spark" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#d0bcff" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#d0bcff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#activity-spark)" />
      <path d={line} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

interface TimelineCardProps {
  event: ActivityEvent;
  busy: boolean;
  outcome: string | null;
  onInspect: (event: ActivityEvent) => void;
  onDecide: (event: ActivityEvent, allow: boolean) => void;
}

function TimelineCard({ event, busy, outcome, onInspect, onDecide }: TimelineCardProps) {
  const style = outcomeStyle(event.outcome);
  const icon = CATEGORY_ICON[event.category] ?? 'bolt';
  const permissionId = permissionIdOf(event.id);
  const resolvable =
    permissionId !== null &&
    event.outcome === 'PENDING' &&
    event.payload.resolvable === true;

  return (
    <div className="group relative rounded-xl bg-surface-container-low hover:bg-surface-container p-space-md transition-all shadow-sm flex flex-col gap-space-sm">
      <div className="flex items-start justify-between gap-space-md">
        <div className="flex items-center gap-space-sm flex-wrap min-w-0">
          <span className={`px-2 py-0.5 rounded font-label-mono-xs text-label-mono-xs font-semibold flex items-center gap-1.5 ${style.badge}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
            {event.outcome}
          </span>
          <span className="font-label-mono-sm text-label-mono-sm text-on-surface font-medium">{shortRef(event.id)}</span>
          <span className="text-outline font-label-mono-xs text-label-mono-xs">{formatTime(event.timestamp)}</span>
          <span className="px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-label-mono-xs text-label-mono-xs">
            {event.kind}
          </span>
          {event.risk_level && (
            <span className={`px-1.5 py-0.5 rounded bg-surface-container-high font-label-mono-xs text-label-mono-xs ${riskClass(event.risk_level)}`}>
              RIESGO {event.risk_level}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => onInspect(event)}
          className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity px-2 py-1 rounded bg-surface-bright text-on-surface font-label-mono-xs text-label-mono-xs flex items-center gap-1 shrink-0"
        >
          <span>AUDIT PAYLOAD</span>
          <span className="material-symbols-outlined text-[13px]">arrow_outward</span>
        </button>
      </div>

      <div className="flex items-center gap-2">
        <span className={`material-symbols-outlined text-[18px] ${style.text}`}>{icon}</span>
        <h3 className="font-headline-sm text-headline-sm text-on-surface">{event.title}</h3>
      </div>

      {(event.detail || event.source || event.reference) && (
        <div className="flex flex-wrap items-center gap-2 font-body-md text-body-md text-on-surface-variant">
          {event.source && (
            <code className="px-1.5 py-0.5 rounded bg-surface-container-highest font-code-base text-code-base text-secondary">
              {event.source}
            </code>
          )}
          {event.reference && (
            <code className="px-1.5 py-0.5 rounded bg-surface-container-highest font-code-base text-code-base text-on-surface">
              {event.reference}
            </code>
          )}
          {event.detail && <span className="leading-relaxed">{event.detail}</span>}
        </div>
      )}

      {resolvable && (
        <div className="flex flex-wrap items-center justify-between gap-space-sm p-space-sm bg-surface-container rounded-lg">
          <div className="flex items-center gap-2 text-on-surface font-label-mono-sm text-label-mono-sm">
            <span className="material-symbols-outlined text-secondary text-[16px]">rule</span>
            <span>Requiere confirmación explícita del operador</span>
          </div>
          <div className="flex items-center gap-space-xs">
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide(event, false)}
              className="px-space-md py-1 bg-surface-container-high hover:bg-surface-bright disabled:opacity-50 text-on-surface rounded font-label-mono-xs text-label-mono-xs transition-colors"
            >
              Rechazar
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide(event, true)}
              className="px-space-md py-1 bg-primary hover:bg-primary-container disabled:opacity-50 text-on-primary rounded font-label-mono-xs text-label-mono-xs font-semibold transition-all shadow-sm"
            >
              {busy ? 'Resolviendo…' : 'Aprobar acción'}
            </button>
          </div>
        </div>
      )}

      {outcome && (
        <div className="p-space-xs px-space-sm rounded bg-surface-container font-code-base text-label-mono-sm text-on-surface-variant">
          {outcome}
        </div>
      )}
    </div>
  );
}

function MetricTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint: string;
  tone: string;
}) {
  return (
    <div className="flex flex-col p-space-md rounded-lg bg-surface-container">
      <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">{label}</span>
      <span className={`font-headline-lg text-headline-lg mt-1 font-semibold ${tone}`}>{value}</span>
      <span className="font-label-mono-xs text-label-mono-xs text-outline mt-1">{hint}</span>
    </div>
  );
}

export default function Activity() {
  const [range, setRange] = useState<ActivityWindow>('24h');
  const [live, setLive] = useState(true);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('ALL');
  const [status, setStatus] = useState('ALL');
  const [inspect, setInspect] = useState<ActivityEvent | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, string>>({});

  const { data, loading, error, reload } = useAsyncData(() => activityApi.get(range), [range]);

  // Poll while live and the tab is visible. `reload` is stable (memoised in the
  // hook), so the interval survives re-renders and is only re-created when the
  // toggle flips.
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') reload();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [live, reload]);

  const events = useMemo(() => data?.events ?? [], [data]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return events.filter((event) => {
      if (category === 'ERRORS') {
        if (event.outcome !== 'DENIED' && event.outcome !== 'ERROR') return false;
      } else if (category !== 'ALL' && event.category !== category) {
        return false;
      }
      if (status !== 'ALL' && event.outcome !== status) return false;
      if (needle) {
        const haystack = `${event.title} ${event.detail} ${event.source ?? ''} ${
          event.reference ?? ''
        } ${event.kind}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [events, category, status, query]);

  const summary = data?.summary;
  const audit = data?.audit;
  const categories: ActivityCategoryCount[] = summary?.categories ?? [];
  const successRate =
    summary && summary.success_rate !== null ? `${(summary.success_rate * 100).toFixed(1)}%` : 'NO EXPUESTO';

  const decide = async (event: ActivityEvent, allow: boolean) => {
    const permissionId = permissionIdOf(event.id);
    if (!permissionId || !event.agent_run_id) return;
    setBusy(event.id);
    setDecisionError(null);
    try {
      if (allow) await permissionsApi.approveRequest(event.agent_run_id, permissionId);
      else await permissionsApi.rejectRequest(event.agent_run_id, permissionId);
      setOutcomes((prev) => ({
        ...prev,
        [event.id]: allow
          ? 'Acción autorizada. El run se reanuda y vuelve a pasar por el Trust Engine.'
          : 'Solicitud denegada. El run observa el rechazo y puede continuar.',
      }));
      reload();
    } catch (caught) {
      setDecisionError(caught instanceof ApiError ? caught.message : 'La decisión ha fallado.');
    } finally {
      setBusy(null);
    }
  };

  const exportJson = () =>
    download('activity.json', JSON.stringify(filtered, null, 2), 'application/json');
  const exportCsv = () => download('activity.csv', toCsv(filtered), 'text/csv');

  return (
    <div className="flex flex-col w-full">
      <div className="px-margin pt-space-lg pb-space-xl flex flex-col gap-space-lg max-w-[1720px] mx-auto w-full">
        {/* Hero */}
        <div className="relative bg-surface-container-low rounded-xl p-space-lg overflow-hidden shadow-sm">
          <div className="absolute -right-20 -top-24 w-96 h-96 rounded-full bg-secondary/5 blur-3xl pointer-events-none" />
          <div className="relative z-10 flex flex-col xl:flex-row xl:items-end justify-between gap-space-lg">
            <div className="flex flex-col gap-space-xs max-w-3xl">
              <div className="flex flex-wrap items-center gap-space-sm">
                <span className="px-2 py-0.5 rounded bg-surface-container-high font-label-mono-xs text-label-mono-xs text-secondary tracking-widest uppercase">
                  AUDIT &amp; RUNTIME TELEMETRY
                </span>
                <span className="text-outline font-label-mono-xs text-label-mono-xs">/</span>
                <span className="font-label-mono-xs text-label-mono-xs text-outline tracking-wider">
                  GET /api/v1/activity
                </span>
              </div>
              <h1 className="font-headline-xl text-headline-xl text-on-surface tracking-tight font-semibold mt-1">
                Registro de Actividad y Auditoría
              </h1>
              <p className="font-body-md text-body-md text-on-surface-variant">
                Trazabilidad de decisiones del Trust Engine, aprobaciones, runs, invocaciones de
                herramientas y memoria — fusionadas desde las fuentes reales del backend y acotadas a
                tu usuario.
              </p>
            </div>

            <div className="flex items-center gap-space-sm shrink-0">
              <button
                type="button"
                onClick={() => setLive((value) => !value)}
                title="Alterna el refresco periódico de la traza"
                className="flex items-center gap-2 px-space-md py-1.5 rounded-lg bg-surface-container-high text-on-surface text-label-mono-sm font-label-mono-sm hover:bg-surface-bright transition-all shadow-sm"
              >
                <span className="relative flex h-2 w-2">
                  {live && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-tertiary opacity-75" />}
                  <span className={`relative inline-flex rounded-full h-2 w-2 ${live ? 'bg-tertiary' : 'bg-outline'}`} />
                </span>
                <span className={live ? 'text-tertiary font-semibold tracking-wide' : 'text-outline tracking-wide'}>
                  {live ? 'EN VIVO' : 'PAUSADO'}
                </span>
              </button>
              <div className="flex items-center rounded-lg bg-surface-container p-0.5">
                <button
                  type="button"
                  onClick={exportJson}
                  className="px-space-md py-1.5 rounded font-label-mono-sm text-label-mono-sm text-on-surface hover:bg-surface-container-high transition-colors flex items-center gap-1.5"
                >
                  <span className="material-symbols-outlined text-[15px]">file_download</span>
                  <span>Exportar</span>
                </button>
                <span className="text-outline-variant font-label-mono-xs text-label-mono-xs px-1">|</span>
                <button type="button" onClick={exportJson} className="px-2 py-1.5 rounded font-label-mono-xs text-label-mono-xs text-on-surface-variant hover:bg-surface-container-high uppercase">
                  JSON
                </button>
                <button type="button" onClick={exportCsv} className="px-2 py-1.5 rounded font-label-mono-xs text-label-mono-xs text-on-surface-variant hover:bg-surface-container-high uppercase">
                  CSV
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Storage degradation banner */}
        {data && !data.storage_available && (
          <div className="rounded-xl bg-error-container/20 border border-error/30 p-space-md flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-error text-[18px]">database_off</span>
            <span className="font-body-sm text-body-sm text-on-surface">
              Almacenamiento no disponible: los runs, acciones, aprobaciones y memorias no se pudieron
              leer. Solo se muestra la traza de autorización en memoria.
            </span>
          </div>
        )}

        {decisionError && <ErrorRow message={decisionError} />}

        {/* Control deck */}
        <div className="rounded-xl bg-surface-container-low p-space-md flex flex-col gap-space-md shadow-sm">
          <div className="flex flex-col lg:flex-row gap-space-md items-stretch lg:items-center justify-between">
            <div className="relative flex-1">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline">
                search
              </span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filtrar eventos por texto, herramienta, skill o run…"
                className="w-full pl-10 pr-4 py-2 bg-surface-container-lowest rounded-lg font-code-base text-code-base text-on-surface placeholder-outline focus:outline-none focus:ring-1 focus:ring-primary transition-all"
              />
            </div>

            <div className="flex flex-wrap items-center gap-space-sm">
              <div className="flex items-center bg-surface-container-lowest rounded-lg p-0.5 text-label-mono-xs font-label-mono-xs">
                {WINDOWS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setRange(option.value)}
                    className={`px-space-md py-1 rounded transition-colors ${
                      range === option.value
                        ? 'bg-surface-container-high text-on-surface font-medium'
                        : 'text-on-surface-variant hover:text-on-surface'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div className="relative">
                <select
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                  className="appearance-none bg-surface-container-lowest text-on-surface font-body-sm text-body-sm pl-3 pr-8 py-2 rounded-lg cursor-pointer focus:outline-none"
                >
                  {STATUSES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <span className="material-symbols-outlined absolute right-2.5 top-1/2 -translate-y-1/2 text-[16px] text-outline pointer-events-none">
                  expand_more
                </span>
              </div>

              <button
                type="button"
                title="Limpiar filtros"
                onClick={() => {
                  setQuery('');
                  setCategory('ALL');
                  setStatus('ALL');
                  setRange('24h');
                }}
                className="p-2 bg-surface-container-lowest text-outline hover:text-on-surface rounded-lg transition-colors flex items-center justify-center"
              >
                <span className="material-symbols-outlined text-[18px]">restart_alt</span>
              </button>
            </div>
          </div>

          <div className="flex items-center gap-space-xs overflow-x-auto pb-0.5">
            <button
              type="button"
              onClick={() => setCategory('ALL')}
              className={`flex items-center gap-2 px-space-md py-1 rounded-lg whitespace-nowrap transition-all font-body-sm text-body-sm ${
                category === 'ALL' ? 'bg-surface-bright text-on-surface font-medium' : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
              <span>Todos</span>
              <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant">
                {summary?.total ?? 0}
              </span>
            </button>

            {categories.map((item) => (
              <button
                key={item.category}
                type="button"
                onClick={() => setCategory(item.category)}
                className={`flex items-center gap-2 px-space-md py-1 rounded-lg whitespace-nowrap transition-all font-body-sm text-body-sm ${
                  category === item.category
                    ? 'bg-surface-bright text-on-surface font-medium'
                    : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${CATEGORY_COLOR[item.category] ?? 'bg-outline'}`} />
                <span>{item.label}</span>
                <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container text-outline">
                  {item.count}
                </span>
              </button>
            ))}

            <button
              type="button"
              onClick={() => setCategory('ERRORS')}
              className={`flex items-center gap-2 px-space-md py-1 rounded-lg whitespace-nowrap transition-all font-body-sm text-body-sm ${
                category === 'ERRORS' ? 'bg-surface-bright text-on-surface font-medium' : 'bg-surface-container-low text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-error" />
              <span>Errores &amp; Denegaciones</span>
              <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container text-error">
                {(summary?.denied ?? 0) + (summary?.error ?? 0)}
              </span>
            </button>
          </div>
        </div>

        {/* Workspace */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg items-start">
          {/* Timeline */}
          <div className="xl:col-span-8 flex flex-col gap-space-sm">
            <div className="flex items-center justify-between px-space-xs mb-1 gap-space-sm">
              <div className="flex items-center gap-space-sm">
                <span className="font-label-mono-sm text-label-mono-sm uppercase text-outline">
                  SECUENCIA DE AUDITORÍA
                </span>
                <span className="w-1 h-1 rounded-full bg-outline" />
                <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                  {range.toUpperCase()} · {filtered.length} EVENTOS
                </span>
              </div>
              <span className="font-label-mono-xs text-label-mono-xs text-outline">
                {live ? 'Sondeo automático cada 15 s' : 'Refresco manual'}
              </span>
            </div>

            {loading && !data ? (
              <LoadingRow label="Cargando traza de actividad…" />
            ) : error && !data ? (
              <ErrorRow message={error} onRetry={reload} />
            ) : filtered.length === 0 ? (
              <EmptyRow message="No hay actividad que coincida con los filtros en esta ventana." />
            ) : (
              filtered.map((event) => (
                <TimelineCard
                  key={event.id}
                  event={event}
                  busy={busy === event.id}
                  outcome={outcomes[event.id] ?? null}
                  onInspect={setInspect}
                  onDecide={decide}
                />
              ))
            )}

            <div className="flex items-center justify-between py-space-md px-space-xs text-outline font-label-mono-xs text-label-mono-xs">
              <span>
                Mostrando {filtered.length} de {summary?.total ?? 0} eventos
                {data?.truncated ? ' (ventana truncada)' : ''}
              </span>
              <button
                type="button"
                onClick={reload}
                className="px-space-md py-1.5 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface transition-colors flex items-center gap-1"
              >
                <span className="material-symbols-outlined text-[14px]">refresh</span>
                <span>Recargar</span>
              </button>
            </div>
          </div>

          {/* Cockpit */}
          <div className="xl:col-span-4 flex flex-col gap-space-lg">
            <div className="rounded-xl bg-surface-container-low p-space-lg flex flex-col gap-space-lg shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-[20px]">analytics</span>
                  <h2 className="font-headline-sm text-headline-sm text-on-surface">Métricas de Actividad</h2>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant uppercase">
                  {range}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-space-md">
                <MetricTile
                  label="Total Eventos"
                  value={summary?.total ?? 0}
                  hint={`${summary?.resolved ?? 0} con veredicto`}
                  tone="text-on-surface"
                />
                <MetricTile
                  label="Tasa de Éxito"
                  value={successRate}
                  hint={
                    summary && summary.success_rate !== null
                      ? `${summary.success} de ${summary.resolved} resueltos`
                      : 'Sin eventos resueltos'
                  }
                  tone="text-tertiary"
                />
                <MetricTile
                  label="Frenos de Seguridad"
                  value={summary?.denied ?? 0}
                  hint="Trust Engine DENY / BLOCK"
                  tone="text-error"
                />
                <MetricTile
                  label="Pendientes"
                  value={summary?.pending ?? 0}
                  hint="esperando decisión"
                  tone="text-secondary"
                />
              </div>

              <div className="flex flex-col gap-space-xs">
                <div className="flex items-center justify-between text-outline font-label-mono-xs text-label-mono-xs">
                  <span>
                    DENSIDAD {summary && summary.bucket_seconds >= 86400 ? 'DIARIA' : 'HORARIA'}
                  </span>
                  <span>PEAK: {summary?.density_peak ?? 0} ev</span>
                </div>
                <div className="w-full rounded bg-surface-container-lowest p-2">
                  <Sparkline values={summary?.density ?? []} peak={summary?.density_peak ?? 0} />
                </div>
              </div>

              <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
                Latencia, tokens y tamaño de payload: <span className="text-on-surface-variant">NO EXPUESTO</span>. El
                backend no registra telemetría de ejecución por acción.
              </p>
            </div>

            <div className="rounded-xl bg-surface-container-low p-space-lg flex flex-col gap-space-md shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[20px]">pie_chart</span>
                  <h2 className="font-headline-sm text-headline-sm text-on-surface">Distribución de Eventos</h2>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs text-outline">POR CATEGORÍA</span>
              </div>

              <div className="w-full h-3 rounded-full bg-surface-container overflow-hidden flex">
                {categories.map((item) => {
                  const total = summary?.total ?? 0;
                  const width = total > 0 ? (item.count / total) * 100 : 0;
                  if (width <= 0) return null;
                  return (
                    <div
                      key={item.category}
                      className={`h-full ${CATEGORY_COLOR[item.category] ?? 'bg-outline'}`}
                      style={{ width: `${width}%` }}
                      title={`${item.label} ${item.count}`}
                    />
                  );
                })}
              </div>

              <div className="flex flex-col gap-space-sm pt-space-xs font-body-sm text-body-sm">
                {categories.map((item) => {
                  const total = summary?.total ?? 0;
                  const pct = total > 0 ? Math.round((item.count / total) * 100) : 0;
                  return (
                    <div key={item.category} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`w-2.5 h-2.5 rounded ${CATEGORY_COLOR[item.category] ?? 'bg-outline'}`} />
                        <span className="text-on-surface">{item.label}</span>
                      </div>
                      <div className="flex items-center gap-2 font-label-mono-xs text-label-mono-xs">
                        <span className="text-outline">{item.count} ev</span>
                        <span className="text-on-surface font-semibold">{pct}%</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="rounded-xl bg-surface-container-low p-space-lg flex flex-col gap-space-md shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-outline text-[20px]">database</span>
                  <h2 className="font-headline-sm text-headline-sm text-on-surface">Retención &amp; Archivo</h2>
                </div>
                <span className="px-2 py-0.5 rounded bg-surface-container font-label-mono-xs text-label-mono-xs text-secondary">
                  EN MEMORIA
                </span>
              </div>

              <p className="font-body-sm text-body-sm text-on-surface-variant">
                {audit?.note ??
                  'La traza de autorización vive en memoria del proceso: acotada y no persistente.'}
              </p>

              <div className="grid grid-cols-2 gap-space-sm">
                <div className="p-space-sm rounded bg-surface-container flex flex-col">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Entradas retenidas</span>
                  <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                    {audit?.retained_entries ?? 0}
                  </span>
                </div>
                <div className="p-space-sm rounded bg-surface-container flex flex-col">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Capacidad del anillo</span>
                  <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                    {audit?.retention_capacity ?? 0}
                  </span>
                </div>
              </div>

              <div className="p-space-sm rounded bg-surface-container flex items-center justify-between font-label-mono-xs text-label-mono-xs text-outline">
                <span>
                  Política de retención configurable: <strong className="text-on-surface-variant">NO EXPUESTO</strong>
                </span>
                <span className="text-outline">Purga: no disponible</span>
              </div>
            </div>

            <div className="p-space-md rounded-xl bg-surface-container-lowest flex items-center justify-between font-label-mono-xs text-label-mono-xs">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${data?.storage_available ? 'bg-tertiary' : 'bg-error'}`} />
                <span className="text-on-surface-variant">
                  AUDIT_WRITER_THREAD / IOPS / PID: NO EXPUESTO
                </span>
              </div>
              <span className="text-outline">
                {data ? `SYNC ${formatStamp(data.generated_at)}` : 'SIN SYNC'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Payload inspector */}
      {inspect && (
        <div
          className="fixed inset-0 z-50 bg-surface-container-lowest/80 backdrop-blur-md flex items-center justify-center p-space-lg"
          onClick={() => setInspect(null)}
          role="presentation"
        >
          <div
            className="w-full max-w-2xl bg-surface-container-low rounded-xl shadow-2xl p-space-lg flex flex-col gap-space-md"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-label-mono-sm text-label-mono-sm">
                <span className="material-symbols-outlined text-secondary text-[20px]">terminal</span>
                <span className="text-on-surface font-semibold">
                  Trazabilidad: <span className="text-primary">{shortRef(inspect.id)}</span>
                </span>
              </div>
              <button
                type="button"
                onClick={() => setInspect(null)}
                className="text-outline hover:text-on-surface p-1 rounded hover:bg-surface-container"
              >
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-space-sm font-label-mono-xs text-label-mono-xs">
              <span className="px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant">{inspect.category}</span>
              <span className="px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant">{inspect.kind}</span>
              <span className={`px-2 py-0.5 rounded ${outcomeStyle(inspect.outcome).badge}`}>{inspect.outcome}</span>
              <span className="text-outline">{formatStamp(inspect.timestamp)}</span>
            </div>

            <div className="rounded-lg bg-surface-container-lowest p-space-md font-code-base text-code-base text-on-surface max-h-96 overflow-y-auto">
              <pre className="text-outline whitespace-pre-wrap break-words">
                {JSON.stringify(inspect.payload, null, 2)}
              </pre>
            </div>

            <div className="flex items-center justify-end pt-2">
              <button
                type="button"
                onClick={() => setInspect(null)}
                className="px-space-md py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-mono-sm text-label-mono-sm"
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
