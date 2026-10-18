import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAsyncData } from '../hooks/useAsyncData';
import { useOverview } from '../hooks/useOverview';
import { agentApi } from '../services/api/agentApi';
import { permissionsApi } from '../services/api/permissionsApi';
import { healthApi } from '../services/api/healthApi';
import { ApiError } from '../services/api/apiClient';
import { EmptyRow, ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { AgentRunResponse, OverviewRun, PermissionRequest } from '../types';

const ACTIVE = new Set(['CREATED', 'CONTEXT_LOADING', 'PLANNING', 'EXECUTING', 'OBSERVING']);

function runStatusMeta(status: string): { label: string; tone: string; dot: string; pulse: boolean } {
  if (status === 'COMPLETED') return { label: 'COMPLETED', tone: 'text-tertiary', dot: 'bg-tertiary', pulse: false };
  if (status === 'WAITING_PERMISSION') return { label: 'EN ESPERA AUTH', tone: 'text-primary', dot: 'bg-primary', pulse: true };
  if (status === 'FAILED' || status === 'BLOCKED' || status === 'CANCELLED')
    return { label: status, tone: 'text-error', dot: 'bg-error', pulse: false };
  return { label: status, tone: 'text-secondary', dot: 'bg-secondary', pulse: ACTIVE.has(status) };
}

function stepMeta(status: string): { label: string; icon: string; chip: string; spin: boolean } {
  switch (status) {
    case 'COMPLETED':
      return { label: 'COMPLETADO', icon: 'check_circle', chip: 'bg-tertiary/10 text-tertiary', spin: false };
    case 'EXECUTING':
      return { label: 'PROCESANDO', icon: 'sync', chip: 'bg-secondary/10 text-secondary', spin: true };
    case 'APPROVED':
      return { label: 'APROBADO', icon: 'thumb_up', chip: 'bg-secondary/10 text-secondary', spin: false };
    case 'FAILED':
      return { label: 'FALLIDO', icon: 'error', chip: 'bg-error/15 text-error', spin: false };
    case 'BLOCKED':
      return { label: 'BLOQUEADO', icon: 'shield_lock', chip: 'bg-error/15 text-error', spin: false };
    default:
      return { label: 'PENDIENTE', icon: 'hourglass_empty', chip: 'bg-surface-container text-outline', spin: false };
  }
}

function formatMoment(iso: string | undefined): string {
  if (!iso) return '--';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '--' : date.toLocaleString();
}

export default function AgentRuns() {
  const { runId } = useParams();
  return <RunsWorkspace routeRunId={runId ?? null} />;
}

function RunsWorkspace({ routeRunId }: { routeRunId: string | null }) {
  const navigate = useNavigate();
  const { data: overview, loading } = useOverview();
  const runtime = useAsyncData(() => healthApi.runtime(), []);

  const [statusFilter, setStatusFilter] = useState('ALL');
  const [query, setQuery] = useState('');
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const runs = overview?.runs.items ?? [];
  const selectedId = routeRunId ?? runs[0]?.run_id ?? null;

  const counts = {
    active: runs.filter((run) => ACTIVE.has(run.status) || run.status === 'WAITING_PERMISSION').length,
    completed: runs.filter((run) => run.status === 'COMPLETED').length,
    waiting: runs.filter((run) => run.status === 'WAITING_PERMISSION').length,
    failed: runs.filter((run) => ['FAILED', 'BLOCKED', 'CANCELLED'].includes(run.status)).length,
  };

  const visible = runs.filter((run) => {
    if (statusFilter === 'ACTIVE' && !(ACTIVE.has(run.status) || run.status === 'WAITING_PERMISSION')) return false;
    if (statusFilter === 'COMPLETED' && run.status !== 'COMPLETED') return false;
    if (statusFilter === 'WAITING' && run.status !== 'WAITING_PERMISSION') return false;
    if (statusFilter === 'FAILED' && !['FAILED', 'BLOCKED', 'CANCELLED'].includes(run.status)) return false;
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return `${run.run_id} ${run.user_request}`.toLowerCase().includes(needle);
  });

  const filters = [
    { key: 'ALL', label: 'Todas', count: runs.length, dot: null as string | null },
    { key: 'ACTIVE', label: 'En curso', count: counts.active, dot: 'bg-secondary' },
    { key: 'COMPLETED', label: 'Completadas', count: counts.completed, dot: 'bg-tertiary' },
    { key: 'WAITING', label: 'En espera auth', count: counts.waiting, dot: 'bg-primary' },
    { key: 'FAILED', label: 'Fallidas', count: counts.failed, dot: 'bg-error' },
  ];

  const createRun = async () => {
    const agentId = overview?.agent?.id;
    if (!agentId || draft.trim() === '') return;
    setCreating(true);
    setCreateError(null);
    try {
      const run = await agentApi.createRun(agentId, draft.trim());
      setDraft('');
      setShowNew(false);
      navigate(`/runs/${run.run_id}`);
    } catch (caught) {
      setCreateError(caught instanceof ApiError ? caught.message : 'No se pudo iniciar la tarea.');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col w-full pb-margin">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-end justify-between gap-space-md py-space-lg mb-space-sm">
        <div className="flex flex-col gap-space-xs">
          <div className="flex items-center gap-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs tracking-widest text-primary uppercase">
              ORCHESTRATION LAYER
            </span>
            <span className="text-outline text-body-sm font-code-base">/</span>
            <span className="font-label-mono-xs text-label-mono-xs text-outline tracking-wider uppercase">
              TRACE-STREAM
            </span>
          </div>
          <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight">
            Historial de Ejecuciones (Agent Runs)
          </h1>
          <p className="font-body-md text-body-md text-on-surface-variant max-w-3xl">
            Trazabilidad y supervisión de las ejecuciones del agente. El backend expone las
            ejecuciones activas vía <span className="font-code-base text-secondary">/api/v1/overview</span> y
            cada detalle por su ID.
          </p>
        </div>
        <div className="flex items-center gap-space-sm self-start xl:self-auto">
          <button
            type="button"
            onClick={runtime.reload}
            className="px-space-md py-2 rounded-lg bg-surface-container-high hover:bg-surface-bright text-on-surface text-body-sm font-body-sm flex items-center gap-1.5 transition-colors"
          >
            <span className="material-symbols-outlined text-[16px] text-on-surface-variant">tune</span>
            <span>Recargar</span>
          </button>
          <button
            type="button"
            disabled={!overview?.agent}
            onClick={() => setShowNew(true)}
            className="px-space-md py-2 rounded-lg bg-primary hover:bg-primary-container disabled:opacity-50 text-on-primary text-body-sm font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
          >
            <span className="material-symbols-outlined text-[18px]">add</span>
            <span>Iniciar Nueva Tarea</span>
          </button>
        </div>
      </div>

      {createError && <div className="mb-space-sm"><ErrorRow message={createError} /></div>}

      {/* Search + status filters */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-space-sm bg-surface-container-lowest p-space-sm rounded-lg mb-space-md">
        <div className="flex-1 flex items-center gap-space-sm bg-surface-container-low px-space-md py-1.5 rounded">
          <span className="material-symbols-outlined text-outline text-[18px]">search</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="bg-transparent border-none outline-none font-body-sm text-body-sm text-on-surface placeholder:text-outline w-full"
            placeholder="Buscar ejecuciones por ID o solicitud…"
          />
          <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container text-outline">
            FILTER
          </span>
        </div>
        <div className="flex items-center overflow-x-auto gap-1 py-0.5">
          {filters.map((filter) => (
            <button
              key={filter.key}
              type="button"
              onClick={() => setStatusFilter(filter.key)}
              className={`px-space-sm py-1 rounded font-label-mono-xs text-label-mono-xs uppercase flex items-center gap-1 whitespace-nowrap transition-colors ${
                statusFilter === filter.key
                  ? 'bg-surface-container-high text-on-surface font-semibold'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
            >
              {filter.dot && <span className={`w-1.5 h-1.5 rounded-full ${filter.dot}`} />}
              <span>{filter.label}</span>
              <span className="px-1 rounded bg-surface-container-high text-on-surface-variant">{filter.count}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-md items-start">
        {/* Execution queue */}
        <div className="xl:col-span-5 flex flex-col gap-space-sm">
          <div className="flex items-center justify-between px-space-xs">
            <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
              <span>COLA DE EJECUCIÓN</span>
              <span>·</span>
              <span>{runs.length} ACTIVAS</span>
            </div>
            <div className="flex items-center gap-1 text-on-surface-variant font-label-mono-xs text-label-mono-xs">
              <span className="material-symbols-outlined text-[14px]">refresh</span>
              <span>Auto-sync 10s</span>
            </div>
          </div>

          {loading ? (
            <LoadingRow label="Cargando ejecuciones…" />
          ) : runs.length === 0 ? (
            <EmptyRow message="No hay ejecuciones activas. El backend no expone un historial completo, solo las ejecuciones en curso." />
          ) : visible.length === 0 ? (
            <EmptyRow message="Ninguna ejecución coincide con el filtro." />
          ) : (
            visible.map((run: OverviewRun) => {
              const meta = runStatusMeta(run.status);
              const isSelected = run.run_id === selectedId;
              return (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => navigate(`/runs/${run.run_id}`)}
                  className={`p-space-md rounded-lg flex flex-col gap-space-xs text-left relative overflow-hidden transition-colors ${
                    isSelected
                      ? 'bg-surface-container-high'
                      : 'bg-surface-container-low hover:bg-surface-container'
                  }`}
                >
                  {isSelected && <span className={`absolute left-0 top-0 bottom-0 w-1 ${meta.dot}`} />}
                  <div className="flex items-center justify-between gap-space-sm">
                    <div className="flex items-center gap-space-xs min-w-0">
                      <span className="font-code-base text-code-base font-semibold text-on-surface">
                        #{run.run_id.slice(0, 8)}
                      </span>
                    </div>
                    <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container-lowest font-label-mono-xs text-label-mono-xs ${meta.tone}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${meta.dot} ${meta.pulse ? 'animate-pulse' : ''}`} />
                      <span>{meta.label}</span>
                    </div>
                  </div>
                  <h3 className="font-body-lg text-body-lg font-medium text-on-surface line-clamp-2">
                    {run.user_request}
                  </h3>
                  <div className="flex items-center justify-between text-outline font-label-mono-xs text-label-mono-xs pt-0.5">
                    <span>Creada: {formatMoment(run.created_at)}</span>
                    <span>Act.: {formatMoment(run.updated_at)}</span>
                  </div>
                </button>
              );
            })
          )}
        </div>

        {/* Detail */}
        <div className="xl:col-span-7 flex flex-col gap-space-md">
          {selectedId ? (
            <RunDetail
              key={selectedId}
              runId={selectedId}
              run={runs.find((item) => item.run_id === selectedId) ?? null}
              modelLabel={overview?.model.model ?? '--'}
              sandboxProvider={runtime.data?.provider ?? '--'}
            />
          ) : (
            <EmptyRow message="Selecciona una ejecución para ver su plan y su traza." />
          )}
        </div>
      </div>

      {/* Start a new task */}
      {showNew && (
        <div
          className="fixed inset-0 z-50 bg-surface-container-lowest/80 backdrop-blur-md flex items-center justify-center p-space-md"
          onClick={() => setShowNew(false)}
        >
          <div
            className="relative w-full max-w-xl rounded-xl bg-surface-container-low shadow-2xl p-space-lg flex flex-col gap-space-md"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-space-sm">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-primary-container/20 flex items-center justify-center text-primary">
                  <span className="material-symbols-outlined text-[20px]">bolt</span>
                </div>
                <div>
                  <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                    Iniciar Nueva Tarea
                  </h2>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">
                    Se ejecutará sobre el agente activo vía el orquestador y el Trust Engine.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowNew(false)}
                className="p-1 rounded text-outline hover:text-on-surface hover:bg-surface-container transition-colors"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>

            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={3}
              placeholder="Describe la tarea para el agente…"
              className="w-full bg-surface-container-lowest px-space-md py-2.5 rounded-lg text-on-surface font-body-md text-body-md placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/60 resize-none"
            />

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowNew(false)}
                className="px-4 py-2 rounded-lg text-on-surface-variant hover:bg-surface-container font-body-sm text-body-sm transition-colors"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={creating || draft.trim() === ''}
                onClick={() => void createRun()}
                className="px-4 py-2 rounded-lg bg-primary-container text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary disabled:opacity-50 transition-all"
              >
                {creating ? 'Ejecutando…' : 'Ejecutar Tarea'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface RunDetailProps {
  runId: string;
  run: OverviewRun | null;
  modelLabel: string;
  sandboxProvider: string;
}

function RunDetail({ runId, run, modelLabel, sandboxProvider }: RunDetailProps) {
  const detail = useAsyncData(() => agentApi.getRun(runId), [runId]);
  const requests = useAsyncData(() => permissionsApi.getPermissionRequests(runId), [runId]);

  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { refresh } = useOverview();

  const data: AgentRunResponse | null = detail.data ?? null;
  const meta = runStatusMeta(data?.status ?? run?.status ?? 'CREATED');
  const actions = data?.actions ?? [];
  const completed = actions.filter((action) => action.status === 'COMPLETED').length;
  const progress = actions.length > 0 ? Math.round((completed / actions.length) * 100) : 0;

  const pending = (requests.data ?? []).filter((request) => request.status === 'PENDING');

  const decide = async (request: PermissionRequest, allow: boolean) => {
    setBusy(request.id);
    setActionError(null);
    try {
      if (allow) await permissionsApi.approveRequest(runId, request.id);
      else await permissionsApi.rejectRequest(runId, request.id);
      detail.reload();
      requests.reload();
      refresh();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : 'La decisión ha fallado.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div className="bg-surface-container-lowest p-space-lg rounded-lg flex flex-col gap-space-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-space-sm">
          <div className="flex flex-col gap-1 min-w-0">
            <div className="flex items-center gap-space-xs flex-wrap">
              <span className="font-code-base text-code-base text-secondary font-semibold">
                #{runId.slice(0, 8)}
              </span>
              <span className="text-outline">·</span>
              <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container-high font-label-mono-xs text-label-mono-xs ${meta.tone}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${meta.dot} ${meta.pulse ? 'animate-pulse' : ''}`} />
                <span>{meta.label}</span>
              </div>
              <span className="px-2 py-0.5 rounded bg-surface-container font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                {sandboxProvider}
              </span>
            </div>
            <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold tracking-tight line-clamp-2">
              {run?.user_request ?? 'Ejecución del agente'}
            </h2>
          </div>
          <button
            type="button"
            onClick={() => {
              detail.reload();
              requests.reload();
            }}
            className="px-2.5 py-1.5 rounded bg-surface-container hover:bg-surface-container-high text-on-surface-variant text-body-sm font-body-sm flex items-center gap-1 transition-colors self-start md:self-auto"
          >
            <span className="material-symbols-outlined text-[16px]">refresh</span>
            <span>Actualizar</span>
          </button>
        </div>

        {actionError && <ErrorRow message={actionError} />}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-space-xs bg-surface-container-low p-space-sm rounded-lg">
          <div className="flex flex-col p-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Estado</span>
            <span className={`font-code-base text-code-base font-semibold mt-0.5 ${meta.tone}`}>
              {data?.status ?? run?.status ?? '--'}
            </span>
          </div>
          <div className="flex flex-col p-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Acciones</span>
            <span className="font-code-base text-code-base font-semibold text-on-surface mt-0.5">
              {completed}/{actions.length}
            </span>
          </div>
          <div className="flex flex-col p-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Runtime Inferencia</span>
            <span className="font-label-mono-xs text-label-mono-xs text-secondary mt-1 truncate">{modelLabel}</span>
          </div>
          <div className="flex flex-col p-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Creada</span>
            <span className="font-label-mono-xs text-label-mono-xs text-on-surface mt-1 truncate">
              {formatMoment(run?.created_at)}
            </span>
          </div>
        </div>

        {/* Pending authorization */}
        {pending.length > 0 && (
          <div className="p-space-sm rounded-lg bg-surface-container border border-primary/30 flex flex-col gap-space-xs">
            {pending.map((request) => (
              <div key={request.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm">
                <div className="flex items-center gap-space-sm min-w-0">
                  <span className="material-symbols-outlined text-primary text-[18px]">gavel</span>
                  <div className="min-w-0">
                    <div className="font-code-base text-code-base text-on-surface truncate">
                      {request.tool_name}
                    </div>
                    <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                      {request.skill_name} · riesgo {request.risk_level}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-space-xs shrink-0">
                  <button
                    type="button"
                    disabled={busy === request.id}
                    onClick={() => void decide(request, false)}
                    className="font-label-mono-xs text-label-mono-xs text-error bg-surface-container-lowest hover:bg-surface-container-high disabled:opacity-50 px-space-sm py-1 rounded transition-colors"
                  >
                    Denegar
                  </button>
                  <button
                    type="button"
                    disabled={busy === request.id}
                    onClick={() => void decide(request, true)}
                    className="font-label-mono-xs text-label-mono-xs text-on-primary bg-primary hover:bg-primary-container disabled:opacity-50 px-space-sm py-1 rounded transition-colors"
                  >
                    Permitir
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Plan */}
        <div className="flex flex-col gap-space-xs">
          <div className="flex items-center justify-between">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
              Plan Orquestado ({actions.length} acciones)
            </span>
            <span className="font-label-mono-xs text-label-mono-xs text-secondary">{progress}% Completado</span>
          </div>
          {detail.loading ? (
            <LoadingRow label="Cargando plan…" />
          ) : detail.error ? (
            <ErrorRow message={detail.error} onRetry={detail.reload} />
          ) : actions.length === 0 ? (
            <EmptyRow message="Esta ejecución no registró acciones." />
          ) : (
            <div className="flex flex-col gap-1.5">
              {actions.map((action, index) => {
                const step = stepMeta(action.status);
                const paramCount = Object.keys(action.arguments).length;
                return (
                  <div
                    key={`${action.tool_name}-${index}`}
                    className="p-space-sm rounded bg-surface-container-low flex items-center justify-between gap-space-sm"
                  >
                    <div className="flex items-center gap-space-sm min-w-0">
                      <span className={`material-symbols-outlined text-[18px] shrink-0 ${step.spin ? 'animate-spin text-secondary' : step.chip.split(' ')[1]}`}>
                        {step.icon}
                      </span>
                      <div className="flex flex-col min-w-0">
                        <span className="font-body-md text-body-md text-on-surface truncate">
                          Paso {index + 1}: {action.tool_name}
                        </span>
                        <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                          {paramCount > 0
                            ? `args: ${Object.keys(action.arguments).join(', ')}`
                            : 'sin argumentos'}
                        </span>
                      </div>
                    </div>
                    <span className={`shrink-0 px-1.5 py-0.5 rounded font-label-mono-xs text-label-mono-xs ${step.chip}`}>
                      {step.label}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Action log (honest: not a live stream) */}
        <div className="flex flex-col gap-space-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-space-xs">
              <span className="w-2 h-2 rounded-full bg-secondary" />
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                REGISTRO DE ACCIONES (NO ES UN STREAM EN VIVO)
              </span>
            </div>
            <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">NO EXPUESTO</span>
          </div>
          <div className="bg-surface-container-lowest p-space-md rounded-lg font-code-base text-code-base flex flex-col gap-1 overflow-x-auto shadow-inner max-h-64">
            {actions.length === 0 ? (
              <span className="text-outline">Sin eventos registrados para esta ejecución.</span>
            ) : (
              actions.map((action, index) => {
                const step = stepMeta(action.status);
                const color = step.chip.split(' ')[1];
                return (
                  <div key={`log-${action.tool_name}-${index}`} className="flex items-start gap-space-sm">
                    <span className="text-outline-variant shrink-0">{String(index + 1).padStart(2, '0')}</span>
                    <span className={`shrink-0 ${color}`}>[{action.status}]</span>
                    <span className="text-on-surface-variant">
                      {action.tool_name}
                      {Object.keys(action.arguments).length > 0 &&
                        ` ${JSON.stringify(action.arguments)}`}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Metrics + trust supervision */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-space-sm">
          <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col gap-space-xs">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">
                Telemetría de Tokens
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">NO EXPUESTO</span>
            </div>
            <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
              El endpoint de detalle no reporta uso de tokens, coste ni memoria del runtime.
            </p>
          </div>
          <div className="bg-surface-container-low p-space-md rounded-lg flex items-center justify-between">
            <div className="flex flex-col gap-1 min-w-0">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">
                Supervisión Trust Engine
              </span>
              <span className="font-body-md text-body-md text-on-surface font-medium truncate">
                {requests.data?.length
                  ? `${requests.data.length} solicitud(es) de permiso`
                  : 'Sin solicitudes de permiso'}
              </span>
              <span className={`font-label-mono-xs text-label-mono-xs ${pending.length ? 'text-primary' : 'text-tertiary'}`}>
                {pending.length
                  ? `${pending.length} pendiente(s) de decisión`
                  : 'Sin bloqueos pendientes'}
              </span>
            </div>
            <div className="w-10 h-10 rounded-full bg-tertiary/10 flex items-center justify-center shrink-0">
              <span className="material-symbols-outlined text-tertiary text-[22px]">verified_user</span>
            </div>
          </div>
        </div>

        {data?.response && (
          <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col gap-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
              Respuesta del Agente
            </span>
            <p className="font-body-md text-body-md text-on-surface whitespace-pre-wrap">{data.response}</p>
          </div>
        )}
      </div>
    </>
  );
}
