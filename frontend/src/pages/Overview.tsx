import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOverview } from '../hooks/useOverview';
import { useAsyncData } from '../hooks/useAsyncData';
import { agentApi } from '../services/api/agentApi';
import { catalogApi } from '../services/api/catalogApi';
import { memoryApi } from '../services/api/memoryApi';
import { permissionsApi } from '../services/api/permissionsApi';
import { ApiError } from '../services/api/apiClient';
import type { MemoryDetail, OverviewAuthorization, OverviewRun } from '../types';

const QUICK_ROUTES: { label: string; prompt: string }[] = [
  { label: 'Revisar PRs de GitHub', prompt: 'Revisar PRs de GitHub' },
  { label: 'Sincronizar calendario', prompt: 'Sincronizar calendario y agenda de hoy' },
  { label: 'Auditar memoria vectorial', prompt: 'Auditar memoria vectorial y balancear nodos' },
  { label: 'Escanear dependencias', prompt: 'Escanear dependencias con CVEs críticos' },
];

const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'BLOCKED', 'CANCELLED']);

function formatUptime(seconds: number | undefined): string {
  if (seconds === undefined) return '--';
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  return `${days}d ${String(hours).padStart(2, '0')}h ${String(minutes).padStart(2, '0')}m`;
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '--';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `Hace ${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `Hace ${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Hace ${hours}h`;
  return `Hace ${Math.round(hours / 24)}d`;
}

function elapsed(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '--';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function riskTone(risk: string): string {
  if (risk === 'HIGH') return 'text-error';
  if (risk === 'MEDIUM') return 'text-primary';
  return 'text-tertiary';
}

function statusTone(status: string): string {
  if (TERMINAL_STATUSES.has(status)) {
    return status === 'COMPLETED' ? 'text-tertiary' : 'text-error';
  }
  return 'text-secondary';
}

export default function Overview() {
  const navigate = useNavigate();
  const { data, loading, error, connected, lastUpdated, refresh } = useOverview();
  const agentId = data?.agent?.id ?? null;

  const [command, setCommand] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandResult, setCommandResult] = useState<string | null>(null);
  const [busyRequest, setBusyRequest] = useState<string | null>(null);

  const memories = useAsyncData(
    () => (agentId ? memoryApi.listMemories(agentId) : Promise.resolve<MemoryDetail[]>([])),
    [agentId],
  );
  const tools = useAsyncData(() => catalogApi.listTools(), []);

  const runCommand = async () => {
    const prompt = command.trim();
    if (prompt === '') return;
    if (!agentId) {
      setCommandError('No hay un agente activo. Crea uno antes de lanzar una ejecución.');
      return;
    }
    setSubmitting(true);
    setCommandError(null);
    setCommandResult(null);
    try {
      const result = await agentApi.createRun(agentId, prompt);
      setCommandResult(result.response ?? `Run ${result.run_id} · ${result.status}`);
      setCommand('');
      refresh();
    } catch (caught) {
      setCommandError(caught instanceof ApiError ? caught.message : 'La ejecución ha fallado.');
    } finally {
      setSubmitting(false);
    }
  };

  const decide = async (request: OverviewAuthorization, allow: boolean) => {
    setBusyRequest(request.request_id);
    try {
      if (allow) {
        await permissionsApi.approveRequest(request.agent_run_id, request.request_id);
      } else {
        await permissionsApi.rejectRequest(request.agent_run_id, request.request_id);
      }
      refresh();
    } catch {
      // The poll on the next tick will reconcile a failed decision; nothing here
      // is worth an alert that would block the operator.
    } finally {
      setBusyRequest(null);
    }
  };

  const topAuthorization = data?.authorizations.items[0] ?? null;
  const activeRun = data?.runs.items[0] ?? null;
  const memoryItems = memories.data ?? [];
  const toolItems = tools.data ?? [];

  const episodic = memoryItems.filter((m) => m.memory_type === 'EPISODIC').length;
  const semantic = memoryItems.filter((m) => m.memory_type === 'SEMANTIC').length;
  const preference = memoryItems.filter((m) => m.memory_type === 'PREFERENCE').length;

  const syncLabel = connected ? 'NEXUS SYNC: 100% NOMINAL' : 'NEXUS SYNC: SIN CONEXIÓN';
  const syncTone = connected ? 'text-tertiary' : 'text-error';

  return (
    <div className="flex flex-col w-full">
      <div className="px-space-lg py-space-md flex flex-col gap-space-lg max-w-[1720px] mx-auto w-full">
        {/* Top Context & Greeting Bar */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md pb-space-xs">
          <div>
            <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-secondary tracking-widest uppercase">
              <span className="inline-block w-2 h-2 rounded-full bg-secondary animate-pulse" />
              <span>Personal AI Workspace · Runtime Activo</span>
            </div>
            <h1 className="font-headline-lg text-headline-lg font-semibold text-on-surface tracking-tight mt-0.5">
              Tu centro de control
            </h1>
            <p className="font-body-md text-body-md text-on-surface-variant">
              Supervisa la actividad autónoma, memoria persistente y vectores de autorización en
              tiempo real.
            </p>
          </div>
          <div className="flex items-center gap-space-sm bg-surface-container-low px-space-md py-1.5 rounded shadow-sm">
            <div className={`flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs ${syncTone}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-tertiary' : 'bg-error'}`} />
              <span>{syncLabel}</span>
            </div>
            <span className="text-outline-variant font-label-mono-xs text-label-mono-xs">/</span>
            <span className="font-label-mono-xs text-label-mono-xs text-outline">
              UPTIME: {formatUptime(data?.system.uptime_seconds)}
            </span>
          </div>
        </div>

        {!connected && (
          <div className="bg-error-container/30 border border-error/40 rounded p-space-md flex items-center gap-space-sm text-on-error-container">
            <span className="material-symbols-outlined text-error text-[18px]">cloud_off</span>
            <div className="flex flex-col">
              <span className="font-body-sm text-body-sm font-medium text-on-surface">
                No se puede alcanzar el backend
              </span>
              <span className="font-label-mono-xs text-label-mono-xs">
                {error ?? 'Revisa que el servidor esté en marcha en la URL configurada.'}
              </span>
            </div>
          </div>
        )}

        {/* Interactive Terminal Command Bar */}
        <div className="bg-surface-container-low rounded p-space-md shadow-md flex flex-col gap-space-sm">
          <div className="flex items-center gap-space-sm bg-surface-container-lowest px-space-md py-space-sm rounded shadow-inner">
            <span className="font-code-base text-code-base text-secondary font-medium select-none">
              nexus&gt;
            </span>
            <input
              id="cmd-input"
              className="w-full bg-transparent border-0 outline-none font-code-base text-code-base text-on-surface placeholder:text-outline focus:outline-none"
              placeholder="Describe un objetivo o instrucción para el agente autónomo..."
              type="text"
              value={command}
              disabled={submitting}
              onChange={(event) => setCommand(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void runCommand();
              }}
            />
            <div className="flex items-center gap-space-xs">
              <kbd className="font-label-mono-xs text-label-mono-xs bg-surface-container px-space-xs py-0.5 rounded text-on-surface-variant select-none">
                ENTER
              </kbd>
              <button
                type="button"
                id="btn-run"
                disabled={submitting}
                onClick={() => void runCommand()}
                className="flex items-center gap-space-xs bg-primary text-on-primary hover:bg-primary-container disabled:opacity-50 px-space-md py-1 rounded font-body-sm text-body-sm font-medium transition-all shadow-sm"
              >
                <span className="material-symbols-outlined text-[16px]">
                  {submitting ? 'hourglass_top' : 'play_arrow'}
                </span>
                <span>{submitting ? 'Ejecutando...' : 'Ejecutar'}</span>
              </button>
            </div>
          </div>
          {commandError && (
            <div className="font-label-mono-xs text-label-mono-xs text-error px-space-xs">
              {commandError}
            </div>
          )}
          {commandResult && (
            <div className="bg-surface-container-lowest rounded p-space-sm font-code-base text-code-base text-on-surface-variant text-[12px] leading-5">
              <span className="text-tertiary">[RESULT]</span> {commandResult}
            </div>
          )}
          <div className="flex items-center gap-space-xs flex-wrap">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider mr-1">
              Rutas Rápidas:
            </span>
            {QUICK_ROUTES.map((route) => (
              <button
                key={route.label}
                type="button"
                onClick={() => setCommand(route.prompt)}
                className="px-space-sm py-0.5 rounded bg-surface-container hover:bg-surface-container-high text-on-surface-variant hover:text-secondary font-label-mono-xs text-label-mono-xs transition-colors"
              >
                {route.label}
              </button>
            ))}
          </div>
        </div>

        {/* 4 Key Telemetry Metrics Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-space-md">
          {/* Metric 1: Modelo Activo */}
          <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm hover:bg-surface-container transition-colors group">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                01 // Modelo Activo
              </span>
              <span
                className={`inline-flex items-center gap-1 font-label-mono-xs text-label-mono-xs bg-surface-container-lowest px-1.5 py-0.5 rounded ${
                  data?.model.configured ? 'text-secondary' : 'text-error'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    data?.model.configured ? 'bg-secondary' : 'bg-error'
                  }`}
                />
                {data?.model.configured ? 'CONECTADO' : 'SIN CREDENCIALES'}
              </span>
            </div>
            <div className="my-space-sm">
              <div className="font-headline-sm text-headline-sm font-semibold text-on-surface tracking-tight truncate">
                {data?.model.model ?? '--'}
              </div>
              <div className="font-body-sm text-body-sm text-on-surface-variant flex items-center gap-1 mt-0.5">
                <span>{data?.model.provider ?? '--'}</span>
                <span className="text-outline-variant">·</span>
                <span className="font-label-mono-xs text-label-mono-xs text-tertiary">
                  LLM {loading ? 'consultando' : 'listo'}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between pt-space-xs text-outline font-label-mono-xs text-label-mono-xs">
              <span>DB: {data?.system.database ?? '--'}</span>
              <span className="text-on-surface font-medium">
                {data?.system.environment ?? '--'}
              </span>
            </div>
          </div>

          {/* Metric 2: Trust Engine */}
          <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm hover:bg-surface-container transition-colors group">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                02 // Trust Engine
              </span>
              <span className="inline-flex items-center gap-1 font-label-mono-xs text-label-mono-xs text-primary bg-surface-container-lowest px-1.5 py-0.5 rounded">
                <span className="material-symbols-outlined text-[13px]">shield_lock</span> ZERO-TRUST
              </span>
            </div>
            <div className="my-space-sm">
              <div className="font-headline-sm text-headline-sm font-semibold text-on-surface tracking-tight">
                {data?.trust.default_decision ?? '--'}
              </div>
              <div className="font-body-sm text-body-sm text-on-surface-variant mt-0.5">
                {data ? `${data.trust.total_grants} permisos · ${data.runtime.provider}` : '--'}
              </div>
            </div>
            <div className="flex items-center justify-between pt-space-xs text-outline font-label-mono-xs text-label-mono-xs">
              <span>ALLOW {data?.trust.allow_grants ?? 0}</span>
              <span className="text-primary font-medium">
                ASK {data?.trust.ask_grants ?? 0} · DENY {data?.trust.deny_grants ?? 0}
              </span>
            </div>
          </div>

          {/* Metric 3: Active Runs */}
          <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm hover:bg-surface-container transition-colors group">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                03 // Runs en Curso
              </span>
              <span className="inline-flex items-center gap-1 font-label-mono-xs text-label-mono-xs text-secondary bg-surface-container-lowest px-1.5 py-0.5 rounded">
                <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-ping" />{' '}
                {data?.runs.active_count ?? 0} ACTIVOS
              </span>
            </div>
            <div className="my-space-sm">
              <div className="font-headline-sm text-headline-sm font-semibold text-on-surface tracking-tight truncate">
                {activeRun ? `Run ${activeRun.run_id.slice(0, 8)}` : 'Sin ejecuciones'}
              </div>
              <div className="font-body-sm text-body-sm text-on-surface-variant mt-0.5 flex items-center justify-between gap-2">
                <span className="truncate">{activeRun?.user_request ?? 'Nada en curso'}</span>
                <span className={`font-label-mono-xs text-label-mono-xs ${activeRun ? statusTone(activeRun.status) : 'text-outline'}`}>
                  {activeRun?.status ?? '--'}
                </span>
              </div>
              <div className="w-full bg-surface-container-lowest h-1.5 rounded-full overflow-hidden mt-1.5">
                <div
                  className="bg-secondary h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, (data?.runs.active_count ?? 0) * 25)}%` }}
                />
              </div>
            </div>
            <div className="flex items-center justify-between pt-space-xs text-outline font-label-mono-xs text-label-mono-xs">
              <span>Worker: Scheduler</span>
              <span className="text-on-surface font-medium">
                {activeRun ? `${elapsed(activeRun.created_at)} activo` : 'inactivo'}
              </span>
            </div>
          </div>

          {/* Metric 4: Autorizaciones Requeridas */}
          <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm hover:bg-surface-container transition-colors group">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                04 // Autorizaciones
              </span>
              <span
                className={`inline-flex items-center gap-1 font-label-mono-xs text-label-mono-xs bg-surface-container-lowest px-1.5 py-0.5 rounded ${
                  (data?.authorizations.pending_count ?? 0) > 0 ? 'text-error' : 'text-tertiary'
                }`}
              >
                <span className="material-symbols-outlined text-[12px]">
                  {(data?.authorizations.pending_count ?? 0) > 0 ? 'warning' : 'check_circle'}
                </span>
                {(data?.authorizations.pending_count ?? 0) > 0 ? 'URGENTE' : 'AL DÍA'}
              </span>
            </div>
            <div className="my-space-sm">
              <div
                className={`font-headline-sm text-headline-sm font-semibold tracking-tight ${
                  (data?.authorizations.pending_count ?? 0) > 0 ? 'text-error' : 'text-on-surface'
                }`}
              >
                {data?.authorizations.pending_count ?? 0} pendientes
              </div>
              <div className="font-body-sm text-body-sm text-on-surface-variant mt-0.5 truncate">
                {topAuthorization
                  ? `${topAuthorization.risk_level} · ${topAuthorization.tool_name}`
                  : 'Ninguna acción bloqueante'}
              </div>
            </div>
            <div className="flex items-center justify-between pt-space-xs text-outline font-label-mono-xs text-label-mono-xs">
              <span>
                {topAuthorization ? `Espera: ${formatRelative(topAuthorization.created_at)}` : '--'}
              </span>
              <button
                type="button"
                onClick={() => navigate('/permissions')}
                className="hover:text-on-surface transition-colors"
              >
                Ver todas →
              </button>
            </div>
          </div>
        </div>

        {/* Main Asymmetric Dashboard Layout (65% / 35%) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg items-start">
          {/* LEFT COLUMN */}
          <div className="lg:col-span-8 flex flex-col gap-space-lg">
            {/* CRITICAL ALERT CARD */}
            {topAuthorization ? (
              <div className="bg-surface-container-low rounded p-space-md shadow-md flex flex-col gap-space-sm relative overflow-hidden">
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-error" />
                <div className="flex items-start justify-between gap-space-md pl-space-xs">
                  <div className="flex items-center gap-space-sm">
                    <div className="w-8 h-8 rounded bg-error-container/40 flex items-center justify-center text-error">
                      <span className="material-symbols-outlined text-[20px]">
                        security_update_warning
                      </span>
                    </div>
                    <div>
                      <div className="flex items-center gap-space-xs">
                        <span className="font-label-mono-xs text-label-mono-xs uppercase text-error font-medium bg-surface-container-lowest px-1.5 py-0.5 rounded">
                          Aprobación Requerida · Riesgo {topAuthorization.risk_level}
                        </span>
                        <span className="font-label-mono-xs text-label-mono-xs text-outline">
                          {topAuthorization.request_id.slice(0, 8)}
                        </span>
                      </div>
                      <h2 className="font-headline-sm text-headline-sm font-semibold text-on-surface mt-0.5">
                        El agente solicita autorización para ejecutar una acción gobernada
                      </h2>
                    </div>
                  </div>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline whitespace-nowrap">
                    {formatRelative(topAuthorization.created_at)}
                  </span>
                </div>
                <p className="font-body-sm text-body-sm text-on-surface-variant pl-space-xs">
                  {topAuthorization.reason}
                </p>
                <div className="ml-space-xs bg-surface-container-lowest rounded p-space-sm flex flex-col md:flex-row md:items-center justify-between gap-space-sm">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-label-mono-xs text-label-mono-xs text-outline">
                      ACCIÓN INVOCADA:
                    </span>
                    <span className="font-code-base text-code-base text-secondary">
                      {topAuthorization.tool_name}
                    </span>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <span className="font-label-mono-xs text-label-mono-xs text-outline">
                      SKILL:
                    </span>
                    <span className="font-code-base text-code-base text-on-surface">
                      {topAuthorization.skill_name}
                    </span>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <span className="font-label-mono-xs text-label-mono-xs text-outline">
                      RUN:
                    </span>
                    <button
                      type="button"
                      onClick={() => navigate(`/runs/${topAuthorization.agent_run_id}`)}
                      className="font-code-base text-code-base text-primary hover:underline text-left"
                    >
                      {topAuthorization.agent_run_id.slice(0, 8)}
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between pl-space-xs pt-space-xs">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    Expira: {new Date(topAuthorization.expires_at).toLocaleString()}
                  </span>
                  <div className="flex items-center gap-space-sm">
                    <button
                      type="button"
                      disabled={busyRequest === topAuthorization.request_id}
                      onClick={() => void decide(topAuthorization, false)}
                      className="bg-surface-container hover:bg-surface-container-high disabled:opacity-50 text-error font-body-sm text-body-sm font-medium px-space-md py-1.5 rounded transition-colors flex items-center gap-1"
                    >
                      <span className="material-symbols-outlined text-[16px]">block</span>
                      <span>Rechazar</span>
                    </button>
                    <button
                      type="button"
                      disabled={busyRequest === topAuthorization.request_id}
                      onClick={() => void decide(topAuthorization, true)}
                      className="bg-primary text-on-primary hover:bg-primary-container disabled:opacity-50 font-body-sm text-body-sm font-medium px-space-md py-1.5 rounded transition-all shadow-md flex items-center gap-1"
                    >
                      <span className="material-symbols-outlined text-[16px]">check_circle</span>
                      <span>Aprobar y Ejecutar</span>
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="bg-surface-container-low rounded p-space-md shadow-sm flex items-center gap-space-sm border border-outline-variant/30">
                <div className="w-8 h-8 rounded bg-surface-container-high flex items-center justify-center text-tertiary">
                  <span className="material-symbols-outlined text-[18px]">verified_user</span>
                </div>
                <div>
                  <div className="font-body-sm text-body-sm font-medium text-on-surface">
                    Sin autorizaciones pendientes
                  </div>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    El firewall no tiene acciones bloqueantes esperando tu decisión.
                  </span>
                </div>
              </div>
            )}

            {/* ACTIVE RUN MONITOR */}
            <div className="bg-surface-container-low rounded p-space-md shadow-sm flex flex-col gap-space-md">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-space-sm">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                    Ejecución Autónoma Vigente
                  </span>
                  <span className="bg-surface-container-lowest text-secondary font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded flex items-center gap-1">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        activeRun ? 'bg-secondary animate-pulse' : 'bg-outline'
                      }`}
                    />
                    STATUS: {activeRun?.status ?? 'IDLE'}
                  </span>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs text-outline font-medium">
                  RUN_ID: {activeRun?.run_id.slice(0, 8) ?? '--'}
                </span>
              </div>
              <div>
                <h3 className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                  {activeRun ? activeRun.user_request : 'No hay ejecuciones activas'}
                </h3>
                <div className="flex flex-wrap items-center gap-space-md text-outline font-body-sm text-body-sm mt-1">
                  <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-[14px]">timer</span>
                    {activeRun ? `${elapsed(activeRun.created_at)} transcurridos` : '--'}
                  </span>
                  <span className="text-outline-variant">·</span>
                  <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-[14px]">schedule</span>
                    Actualizado {activeRun ? formatRelative(activeRun.updated_at) : '--'}
                  </span>
                  {activeRun && (
                    <>
                      <span className="text-outline-variant">·</span>
                      <button
                        type="button"
                        onClick={() => navigate(`/runs/${activeRun.run_id}`)}
                        className="flex items-center gap-1 hover:text-on-surface transition-colors"
                      >
                        <span className="material-symbols-outlined text-[14px]">open_in_new</span>
                        Ver detalle
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className="bg-surface-container-lowest rounded p-space-sm font-code-base text-code-base flex flex-col gap-1 text-on-surface-variant text-[12px] leading-5">
                <div className="flex items-center justify-between text-outline font-label-mono-xs text-label-mono-xs pb-1 mb-1 bg-surface-container-low px-space-xs rounded">
                  <span>ESTADO DEL RUNTIME</span>
                  <span>{connected ? 'STREAM CONECTADO' : 'SIN CONEXIÓN'}</span>
                </div>
                <div className="flex gap-2 text-outline">
                  <span className="text-tertiary">[SYS]</span>
                  <span>
                    Backend {connected ? 'operativo' : 'inalcanzable'} · DB{' '}
                    {data?.system.database ?? '--'} · entorno {data?.system.environment ?? '--'}
                  </span>
                </div>
                <div className="flex gap-2 text-outline">
                  <span className="text-secondary">[LLM]</span>
                  <span>
                    {data?.model.model ?? '--'} vía {data?.model.provider ?? '--'}
                  </span>
                </div>
                <div className="flex gap-2 text-outline">
                  <span className="text-primary">[AUTH]</span>
                  <span>
                    {data?.authorizations.pending_count ?? 0} autorizaciones pendientes ·{' '}
                    {data?.runs.active_count ?? 0} runs activos
                  </span>
                </div>
              </div>
            </div>

            {/* RECENT ACTIVITY FEED */}
            <div className="bg-surface-container-low rounded p-space-md shadow-sm flex flex-col gap-space-md">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                    Flujo de Auditoría
                  </span>
                  <h3 className="font-headline-sm text-headline-sm font-semibold text-on-surface mt-0.5">
                    Actividad Reciente del Sistema
                  </h3>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {lastUpdated ? `ACTUALIZADO ${new Date(lastUpdated).toLocaleTimeString()}` : 'SIN DATOS'}
                </span>
              </div>

              {runList(data?.runs.items ?? []).length === 0 ? (
                <div className="p-space-md text-center font-body-sm text-body-sm text-on-surface-variant bg-surface-container-lowest rounded">
                  Aún no hay ejecuciones registradas para tu usuario.
                </div>
              ) : (
                <div className="flex flex-col gap-space-xs">
                  {runList(data?.runs.items ?? []).map((run) => (
                    <button
                      key={run.run_id}
                      type="button"
                      onClick={() => navigate(`/runs/${run.run_id}`)}
                      className="flex items-center justify-between p-space-sm rounded bg-surface-container-lowest hover:bg-surface-container transition-colors text-left w-full"
                    >
                      <div className="flex items-center gap-space-md">
                        <div className="w-7 h-7 rounded bg-surface-container-high flex items-center justify-center text-secondary">
                          <span className="material-symbols-outlined text-[16px]">schema</span>
                        </div>
                        <div>
                          <div className="flex items-center gap-space-xs font-body-sm text-body-sm font-medium text-on-surface">
                            <span className="truncate max-w-[420px]">{run.user_request}</span>
                          </div>
                          <span className="font-label-mono-xs text-label-mono-xs text-outline">
                            RUN {run.run_id.slice(0, 8)} · {formatRelative(run.updated_at)}
                          </span>
                        </div>
                      </div>
                      <span
                        className={`bg-surface-container font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded ${statusTone(run.status)}`}
                      >
                        {run.status}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* RIGHT COLUMN */}
          <div className="lg:col-span-4 flex flex-col gap-space-lg">
            {/* MEMORY & CONTEXT HEALTH CARD */}
            <div className="bg-surface-container-low rounded p-space-md shadow-sm flex flex-col gap-space-md">
              <div className="flex items-center justify-between">
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                  Subsistema de Memoria
                </span>
                <span
                  className={`font-label-mono-xs text-label-mono-xs bg-surface-container-lowest px-2 py-0.5 rounded flex items-center gap-1 ${
                    memories.error ? 'text-error' : 'text-tertiary'
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      memories.error ? 'bg-error' : 'bg-tertiary'
                    }`}
                  />
                  {memories.error ? 'ERROR' : 'OK'}
                </span>
              </div>
              <div>
                <h3 className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                  Salud del Contexto
                </h3>
                <p className="font-body-sm text-body-sm text-on-surface-variant mt-0.5">
                  Recuerdos indexados para el agente activo.
                </p>
              </div>
              <div className="grid grid-cols-3 gap-space-xs bg-surface-container-lowest p-space-sm rounded">
                <div className="flex flex-col">
                  <span className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                    {episodic}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">
                    Episódicos
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="font-headline-sm text-headline-sm font-semibold text-secondary">
                    {semantic}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">
                    Semánticos
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="font-headline-sm text-headline-sm font-semibold text-primary">
                    {preference}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">
                    Preferencias
                  </span>
                </div>
              </div>
              <div className="flex items-center justify-between bg-surface-container p-space-sm rounded">
                <div className="flex flex-col">
                  <span className="font-body-sm text-body-sm font-medium text-on-surface">
                    {memories.loading ? 'Cargando memoria…' : `${memoryItems.length} recuerdos`}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    {agentId ? `Agent ${agentId.slice(0, 8)}` : 'Sin agente activo'}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => navigate('/memory')}
                  className="font-label-mono-xs text-label-mono-xs text-secondary hover:text-on-surface transition-colors"
                >
                  Abrir →
                </button>
              </div>
            </div>

            {/* CONNECTED TOOLS PANEL */}
            <div className="bg-surface-container-low rounded p-space-md shadow-sm flex flex-col gap-space-md">
              <div className="flex items-center justify-between">
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                  Catálogo de Herramientas
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {toolItems.length} HERRAMIENTAS
                </span>
              </div>
              <h3 className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                Ecosistema MCP
              </h3>
              {tools.error ? (
                <div className="font-label-mono-xs text-label-mono-xs text-error p-space-xs bg-surface-container-lowest rounded">
                  {tools.error}
                </div>
              ) : toolItems.length === 0 ? (
                <div className="font-label-mono-xs text-label-mono-xs text-outline p-space-xs bg-surface-container-lowest rounded">
                  {tools.loading ? 'Cargando catálogo…' : 'Sin herramientas registradas'}
                </div>
              ) : (
                <div className="flex flex-col gap-space-xs">
                  {toolItems.slice(0, 4).map((tool) => (
                    <div
                      key={tool.name}
                      className="flex items-center justify-between p-space-xs bg-surface-container-lowest rounded"
                    >
                      <div className="flex items-center gap-space-xs min-w-0">
                        <span className="material-symbols-outlined text-[16px] text-secondary">
                          construction
                        </span>
                        <span className="font-body-sm text-body-sm text-on-surface truncate">
                          {tool.name}
                        </span>
                      </div>
                      <span
                        className={`font-label-mono-xs text-label-mono-xs bg-surface-container px-1.5 py-0.5 rounded shrink-0 ${riskTone(tool.risk_level)}`}
                      >
                        {tool.risk_level}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* RUNTIME HEALTH */}
            <div className="bg-surface-container-low rounded p-space-md shadow-sm flex flex-col gap-space-sm">
              <div className="flex items-center justify-between">
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                  Sandbox Runtime
                </span>
                <span
                  className={`font-label-mono-xs text-label-mono-xs font-medium ${
                    data?.runtime.available ? 'text-tertiary' : 'text-primary'
                  }`}
                >
                  {data?.runtime.available ? 'DISPONIBLE' : 'NO DISPONIBLE'}
                </span>
              </div>
              <h3 className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                {data?.runtime.provider ?? '--'}
              </h3>
              <div className="w-full bg-surface-container-lowest p-space-sm rounded flex flex-col gap-1">
                <span className="font-code-base text-code-base text-[12px] text-on-surface-variant">
                  {data?.runtime.detail || 'Sin detalle reportado por el runtime.'}
                </span>
                <div className="flex items-center justify-between text-outline font-label-mono-xs text-label-mono-xs pt-1">
                  <span>Cada acción sigue requiriendo ALLOW del Trust Engine</span>
                </div>
              </div>
            </div>

            {/* QUICK SYSTEM SHORTCUTS */}
            <div className="bg-surface-container-low rounded p-space-md shadow-sm flex flex-col gap-space-sm">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                Accesos Directos
              </span>
              <div className="grid grid-cols-2 gap-space-xs">
                <button
                  type="button"
                  onClick={refresh}
                  className="bg-surface-container hover:bg-surface-container-high p-space-sm rounded text-left flex flex-col gap-1 transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px] text-primary">
                    restart_alt
                  </span>
                  <span className="font-body-sm text-body-sm font-medium text-on-surface">
                    Refrescar Estado
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    Releer del backend
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/permissions')}
                  className="bg-surface-container hover:bg-surface-container-high p-space-sm rounded text-left flex flex-col gap-1 transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px] text-secondary">
                    verified_user
                  </span>
                  <span className="font-body-sm text-body-sm font-medium text-on-surface">
                    Permisos
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    Revisar concesiones
                  </span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Show the most recent runs first; the backend returns active ones first. */
function runList(runs: OverviewRun[]): OverviewRun[] {
  return [...runs].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
}
