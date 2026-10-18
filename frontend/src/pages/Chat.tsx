import { useEffect, useMemo, useRef, useState } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { useOverview } from '../hooks/useOverview';
import { agentApi } from '../services/api/agentApi';
import { catalogApi } from '../services/api/catalogApi';
import { permissionsApi } from '../services/api/permissionsApi';
import { ApiError, ApiNetworkError } from '../services/api/apiClient';
import type { AgentActionResponse, AgentRunResponse, PermissionRequest } from '../types';

/** Prompt fragments the operator can drop straight into the input. */
const QUICK_CHIPS = ['/plan', '/search', '/run', '/explain'];

interface Turn {
  id: number;
  prompt: string;
  createdAt: number;
  state: 'running' | 'done' | 'error';
  run?: AgentRunResponse;
  error?: string;
}

interface RecentRun {
  runId: string;
  label: string;
  status: string;
  when: string;
}

function clockTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('es-ES', { hour12: false });
}

function relative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '--';
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function errorText(caught: unknown): string {
  if (caught instanceof ApiNetworkError) return caught.message;
  if (caught instanceof ApiError) return caught.message;
  if (caught instanceof Error) return caught.message;
  return 'La ejecución ha fallado.';
}

function runTone(status: string): string {
  if (status === 'COMPLETED') return 'text-tertiary';
  if (status === 'WAITING_PERMISSION') return 'text-error';
  if (status === 'FAILED' || status === 'BLOCKED' || status === 'CANCELLED') return 'text-error';
  return 'text-secondary';
}

function stepTone(status: string): string {
  if (status === 'COMPLETED' || status === 'APPROVED') return 'text-tertiary';
  if (status === 'FAILED' || status === 'BLOCKED') return 'text-error';
  if (status === 'EXECUTING') return 'text-secondary';
  return 'text-outline';
}

function stepBadgeTone(status: string): string {
  if (status === 'COMPLETED' || status === 'APPROVED') return 'bg-tertiary/20 text-tertiary';
  if (status === 'FAILED' || status === 'BLOCKED') return 'bg-error/20 text-error';
  if (status === 'EXECUTING') return 'bg-secondary/20 text-secondary animate-pulse';
  return 'bg-surface-container-high text-outline';
}

function stepIcon(status: string): string {
  if (status === 'COMPLETED' || status === 'APPROVED') return 'check';
  if (status === 'FAILED') return 'close';
  if (status === 'BLOCKED') return 'block';
  if (status === 'EXECUTING') return 'sync';
  return 'schedule';
}

function actionNarrative(status: string): string {
  switch (status) {
    case 'PROPOSED':
      return 'Propuesta de herramienta, pendiente de autorización';
    case 'APPROVED':
      return 'Autorizada por el operador';
    case 'EXECUTING':
      return 'Ejecutándose';
    case 'COMPLETED':
      return 'Ejecutada correctamente';
    case 'FAILED':
      return 'Ejecución fallida';
    case 'BLOCKED':
      return 'Bloqueada por la política de confianza';
    default:
      return 'Estado desconocido';
  }
}

/** The agent's own account of where the run stands right now. */
function runNarrative(run: AgentRunResponse): string {
  switch (run.status) {
    case 'CREATED':
    case 'CONTEXT_LOADING':
      return 'Cargando contexto y preparando la ejecución…';
    case 'PLANNING':
      return 'Descomponiendo el objetivo en pasos de herramienta…';
    case 'EXECUTING':
    case 'OBSERVING':
      return 'Ejecutando el plan y observando resultados…';
    case 'WAITING_PERMISSION':
      return 'El plan se ha detenido: hay una acción que requiere tu autorización explícita.';
    case 'COMPLETED':
      return run.response ?? 'Ejecución completada.';
    case 'FAILED':
      return run.response ?? 'La ejecución ha fallado.';
    case 'BLOCKED':
      return run.response ?? 'Una acción fue bloqueada por la política de confianza.';
    case 'CANCELLED':
      return 'La ejecución fue cancelada.';
    default:
      return run.response ?? 'Estado desconocido.';
  }
}

function summarize(args: Record<string, unknown>, max = 72): string {
  const text = JSON.stringify(args);
  if (!text) return '{}';
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function riskTone(risk?: string): string {
  if (risk === 'HIGH') return 'text-error';
  if (risk === 'MEDIUM') return 'text-primary';
  return 'text-tertiary';
}

/** The pending permission request behind an ASK run, if any. */
function useRunApproval(runId: string | null) {
  const state = useAsyncData(
    () =>
      runId
        ? permissionsApi.getPermissionRequests(runId)
        : Promise.resolve([] as PermissionRequest[]),
    [runId],
  );
  const pending = (state.data ?? []).find((request) => request.status === 'PENDING') ?? null;
  return { pending, loading: state.loading };
}

function useCountdown(expiresAt: string | undefined): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!expiresAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt]);

  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - now;
  if (Number.isNaN(diff)) return null;
  if (diff <= 0) return 'EXPIRADO';
  const seconds = Math.floor(diff / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function AgentAvatar() {
  return (
    <div className="w-8 h-8 rounded bg-surface-container-highest flex items-center justify-center text-secondary flex-shrink-0 shadow-sm">
      <span className="material-symbols-outlined text-[20px]">smart_toy</span>
    </div>
  );
}

interface RunCardProps {
  turn: Turn;
  deciding: string | null;
  onDecide: (runId: string, permission: 'ALLOW' | 'DENY') => void;
}

function RunCard({ turn, deciding, onDecide }: RunCardProps) {
  const run = turn.run;
  // Hooks must run unconditionally, so the approval read is disabled by passing
  // no run id whenever the run is not actually parked on a question.
  const isWaiting = run?.status === 'WAITING_PERMISSION';
  const approval = useRunApproval(isWaiting ? (run?.run_id ?? null) : null);
  const busy = run ? deciding === run.run_id : false;

  if (turn.state === 'error') {
    return (
      <div className="flex items-start gap-space-md max-w-4xl mr-auto w-full">
        <AgentAvatar />
        <div className="flex-1 bg-error-container/20 border border-error/40 rounded-xl p-space-md flex items-start gap-space-sm">
          <span className="material-symbols-outlined text-error text-[20px]">error</span>
          <div className="flex flex-col gap-0.5">
            <span className="font-body-sm text-body-sm text-on-surface font-medium">
              La ejecución no pudo completarse
            </span>
            <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
              {turn.error}
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-start gap-space-md max-w-4xl mr-auto w-full">
        <AgentAvatar />
        <div className="flex-1 bg-surface-container-low p-space-md rounded-xl flex items-center gap-space-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse" />
          <span className="font-code-base text-code-base text-on-surface-variant">
            El agente está planificando y ejecutando…
          </span>
        </div>
      </div>
    );
  }

  const actions = run.actions;
  const completed = actions.filter((a) => a.status === 'COMPLETED').length;

  return (
    <div className="flex items-start gap-space-md max-w-4xl mr-auto w-full">
      <AgentAvatar />
      <div className="flex-1 flex flex-col gap-space-md min-w-0">
        {/* Header explanation */}
        <div className="bg-surface-container-low p-space-md rounded-xl">
          <div className="flex items-center justify-between mb-2 gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                Autonomous Goal Solver
              </span>
              <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-primary/20 text-primary uppercase font-medium">
                AGENT RUN
              </span>
            </div>
            <span className="font-label-mono-xs text-label-mono-xs text-outline whitespace-nowrap">
              RUN_ID: {run.run_id.slice(0, 12)}
            </span>
          </div>
          <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed">
            {runNarrative(run)}
          </p>
          <div className="mt-2">
            <span
              className={`font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container ${runTone(
                run.status,
              )}`}
            >
              {run.status}
            </span>
          </div>
        </div>

        {/* Execution plan pipeline */}
        <div className="bg-surface-container-low rounded-xl p-space-md flex flex-col gap-space-sm">
          <div className="flex items-center justify-between pb-1">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
              Plan de Acción ({actions.length} {actions.length === 1 ? 'paso' : 'pasos'})
            </span>
            <span className="font-label-mono-xs text-label-mono-xs text-tertiary">
              {completed} / {actions.length} completados
            </span>
          </div>

          {actions.length === 0 ? (
            <div className="font-label-mono-xs text-label-mono-xs text-outline p-space-xs bg-surface-container rounded">
              El agente no propuso acciones de herramienta en esta ejecución.
            </div>
          ) : (
            actions.map((action: AgentActionResponse, index: number) => (
              <div
                key={`${index}-${action.tool_name}`}
                className={`bg-surface-container rounded p-space-sm flex items-center justify-between gap-space-sm ${
                  action.status === 'BLOCKED'
                    ? 'bg-gradient-to-r from-surface-container to-surface-container-high'
                    : ''
                }`}
              >
                <div className="flex items-center gap-space-sm min-w-0">
                  <div
                    className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${stepBadgeTone(
                      action.status,
                    )}`}
                  >
                    <span className="material-symbols-outlined text-[14px]">
                      {stepIcon(action.status)}
                    </span>
                  </div>
                  <div className="flex flex-col min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-body-sm text-body-sm font-medium text-on-surface whitespace-nowrap">
                        Paso {index + 1}: {action.tool_name}
                      </span>
                      <span className="font-code-base text-code-base text-outline text-[11px] truncate">
                        {summarize(action.arguments)}
                      </span>
                    </div>
                    <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                      {actionNarrative(action.status)}
                    </span>
                  </div>
                </div>
                <span
                  className={`font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-high whitespace-nowrap ${stepTone(
                    action.status,
                  )}`}
                >
                  {action.status}
                </span>
              </div>
            ))
          )}
        </div>

        {/* Inline Trust Engine approval guard */}
        {isWaiting && (
          <ApprovalCard run={run} request={approval.pending} busy={busy} onDecide={onDecide} />
        )}
      </div>
    </div>
  );
}

interface ApprovalCardProps {
  run: AgentRunResponse;
  request: PermissionRequest | null;
  busy: boolean;
  onDecide: (runId: string, permission: 'ALLOW' | 'DENY') => void;
}

function ApprovalCard({ run, request, busy, onDecide }: ApprovalCardProps) {
  const countdown = useCountdown(request?.expires_at);

  return (
    <div className="bg-surface-container-high rounded-xl p-space-md flex flex-col gap-space-md shadow-xl">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded bg-error/20 text-error flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="material-symbols-outlined text-[22px]">gavel</span>
        </div>
        <div className="flex flex-col gap-1 flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="font-headline-sm text-headline-sm text-error font-semibold">
              Firewall de Confianza: Autorización Requerida
            </span>
            <span className="font-label-mono-xs text-label-mono-xs bg-surface-container-lowest px-2 py-0.5 rounded text-secondary font-code-base whitespace-nowrap">
              POLÍTICA: TRUST ENGINE
            </span>
          </div>
          <p className="font-body-sm text-body-sm text-on-surface leading-normal">
            {run.question ?? 'El agente solicita autorización para ejecutar una acción gobernada.'}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-space-sm p-space-sm bg-surface-container-low rounded">
        <div className="flex flex-col min-w-0">
          <span className="font-label-mono-xs text-label-mono-xs text-outline">HERRAMIENTA MCP</span>
          <span className="font-code-base text-code-base text-on-surface text-xs font-medium truncate">
            {request?.tool_name ?? '--'}
          </span>
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-label-mono-xs text-label-mono-xs text-outline">NIVEL DE RIESGO</span>
          <span
            className={`font-label-mono-xs text-label-mono-xs font-semibold uppercase ${riskTone(
              request?.risk_level,
            )}`}
          >
            {request?.risk_level ?? 'No reportado'}
          </span>
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-label-mono-xs text-label-mono-xs text-outline">SKILL</span>
          <span className="font-code-base text-code-base text-secondary text-xs truncate">
            {request?.skill_name ?? '--'}
          </span>
        </div>
      </div>

      {request?.reason && (
        <p className="font-body-sm text-body-sm text-on-surface-variant">{request.reason}</p>
      )}

      <div className="bg-surface-container-lowest p-space-sm rounded font-code-base text-code-base text-xs flex flex-col gap-1 overflow-x-auto text-on-surface-variant">
        <span className="text-outline uppercase text-[10px]">PAYLOAD DE LA ACCIÓN (JSON):</span>
        <code className="text-primary-fixed whitespace-pre-wrap">
          {request ? JSON.stringify(request.arguments_summary, null, 2) : '—'}
        </code>
      </div>

      <div className="flex items-center justify-between pt-1 gap-space-sm">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-outline text-[16px]">timer</span>
          <span className="font-label-mono-xs text-label-mono-xs text-outline">
            {countdown ? `Expira en ${countdown}` : 'Sin vencimiento reportado'}
          </span>
        </div>
        <div className="flex items-center gap-space-sm">
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide(run.run_id, 'DENY')}
            className="px-space-md py-1.5 rounded bg-surface-container text-error font-body-sm text-body-sm font-semibold hover:bg-error/20 disabled:opacity-50 transition-colors"
          >
            RECHAZAR ACCIÓN
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide(run.run_id, 'ALLOW')}
            className="px-space-lg py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-container hover:text-on-primary-container shadow-md disabled:opacity-50 transition-all flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-[16px]">verified</span>
            APROBAR Y EJECUTAR
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Chat() {
  const { data: overview, loading: overviewLoading, connected } = useOverview();
  const agentId = overview?.agent?.id ?? null;
  const model = overview?.model;
  const runtime = overview?.runtime;

  const tools = useAsyncData(() => catalogApi.listTools(), []);
  const toolItems = tools.data ?? [];

  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<string | null>(null);

  const counter = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const send = async () => {
    const prompt = input.trim();
    if (prompt === '' || sending) return;
    if (!agentId) {
      setNotice({
        tone: 'error',
        text: 'No hay un agente activo. Crea o activa uno antes de lanzar una ejecución.',
      });
      return;
    }

    const id = ++counter.current;
    setTurns((prev) => [...prev, { id, prompt, createdAt: Date.now(), state: 'running' }]);
    setInput('');
    setSending(true);
    setNotice(null);

    try {
      const run = await agentApi.createRun(agentId, prompt);
      setTurns((prev) =>
        prev.map((turn) => (turn.id === id ? { ...turn, state: 'done', run } : turn)),
      );
      setSelectedRunId(run.run_id);
    } catch (caught) {
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id === id ? { ...turn, state: 'error', error: errorText(caught) } : turn,
        ),
      );
    } finally {
      setSending(false);
    }
  };

  const decide = async (runId: string, permission: 'ALLOW' | 'DENY') => {
    setDeciding(runId);
    setNotice(null);
    try {
      const run = await agentApi.resumeRun(runId, permission);
      setTurns((prev) =>
        prev.map((turn) => (turn.run?.run_id === runId ? { ...turn, state: 'done', run } : turn)),
      );
    } catch (caught) {
      setNotice({ tone: 'error', text: errorText(caught) });
    } finally {
      setDeciding(null);
    }
  };

  const insertChip = (chip: string) => {
    setInput((prev) => (prev ? `${prev} ${chip} ` : `${chip} `));
    inputRef.current?.focus();
  };

  // The inspector follows the selected run when it lives in the conversation,
  // and otherwise falls back to a fresh read of the run id (e.g. an active run
  // picked from the sidebar). GET returns actions but not response/question.
  const turnRuns = useMemo(
    () => turns.map((turn) => turn.run).filter((run): run is AgentRunResponse => Boolean(run)),
    [turns],
  );
  const selectedTurnRun = selectedRunId
    ? turnRuns.find((run) => run.run_id === selectedRunId) ?? null
    : null;
  const needsFetch = selectedRunId !== null && selectedTurnRun === null;
  const fetchedRun = useAsyncData<AgentRunResponse | null>(
    () =>
      needsFetch && selectedRunId ? agentApi.getRun(selectedRunId) : Promise.resolve(null),
    [selectedRunId],
  );
  const defaultRun = turnRuns.length > 0 ? turnRuns[turnRuns.length - 1] : null;
  const inspectedRun = selectedTurnRun ?? (needsFetch ? fetchedRun.data : null) ?? defaultRun;
  const inspectedActions = inspectedRun?.actions ?? [];

  const recentRuns = useMemo<RecentRun[]>(() => {
    const map = new Map<string, RecentRun>();
    turns.forEach((turn) => {
      if (turn.run) {
        map.set(turn.run.run_id, {
          runId: turn.run.run_id,
          label: turn.prompt,
          status: turn.run.status,
          when: 'esta sesión',
        });
      }
    });
    (overview?.runs.items ?? []).forEach((run) => {
      if (!map.has(run.run_id)) {
        map.set(run.run_id, {
          runId: run.run_id,
          label: run.user_request,
          status: run.status,
          when: relative(run.updated_at),
        });
      }
    });
    return Array.from(map.values()).reverse();
  }, [turns, overview]);

  // Keep the newest exchange in view as runs arrive.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns]);

  return (
    <div className="flex h-[calc(100vh-3.5rem)] w-full overflow-hidden">
      {/* Left Column: Context & Sessions */}
      <aside className="w-[280px] flex-shrink-0 bg-surface-container-low flex flex-col justify-between overflow-y-auto">
        <div className="flex flex-col">
          {/* Focused run badge bar */}
          <div className="p-space-md bg-surface-container flex flex-col gap-space-xs">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                EJECUCIÓN EN FOCO
              </span>
              {inspectedRun ? (
                inspectedRun.status === 'WAITING_PERMISSION' ? (
                  <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-error/15 text-error font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-error animate-ping" />
                    AWAITING AUTH
                  </span>
                ) : (
                  <span
                    className={`font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-lowest font-medium ${runTone(
                      inspectedRun.status,
                    )}`}
                  >
                    {inspectedRun.status}
                  </span>
                )
              ) : (
                <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-lowest text-outline">
                  IDLE
                </span>
              )}
            </div>
            <div className="font-label-mono-sm text-label-mono-sm text-on-surface font-semibold flex items-center gap-1.5">
              <span className="text-secondary font-code-base text-code-base">
                {inspectedRun ? `#${inspectedRun.run_id.slice(0, 8)}` : '—'}
              </span>
              <span className="text-outline-variant">·</span>
              <span className="text-primary truncate">{model?.model ?? 'Modelo no disponible'}</span>
            </div>
            <div className="flex items-center gap-2 font-label-mono-xs text-label-mono-xs text-on-surface-variant">
              <span>{model?.provider ?? '—'}</span>
              <span>·</span>
              <span className={runtime?.available ? 'text-tertiary' : 'text-error'}>
                {runtime?.available ? 'runtime listo' : 'runtime no disponible'}
              </span>
            </div>
          </div>

          {/* Context window usage (not exposed by the backend) */}
          <div className="p-space-md flex flex-col gap-space-xs">
            <div className="flex items-center justify-between text-on-surface-variant">
              <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                Ventana de Contexto
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-outline">no expuesto</span>
            </div>
            <div className="w-full bg-surface-container h-1 rounded-full overflow-hidden">
              <div className="bg-secondary h-full rounded-full" style={{ width: '0%' }} />
            </div>
            <span className="font-label-mono-xs text-label-mono-xs text-outline mt-1">
              El backend no reporta consumo de tokens por ejecución.
            </span>
          </div>

          {/* MCP tool hub */}
          <div className="px-space-md py-space-xs flex flex-col gap-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
              HERRAMIENTAS MCP ({toolItems.length} ONLINE)
            </span>
            <div className="flex flex-wrap gap-1.5 mt-0.5">
              {toolItems.length === 0 ? (
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {tools.loading
                    ? 'Cargando catálogo…'
                    : tools.error
                      ? 'Catálogo no disponible'
                      : 'Sin herramientas registradas'}
                </span>
              ) : (
                toolItems.slice(0, 8).map((tool) => (
                  <span
                    key={tool.name}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-container font-label-mono-xs text-label-mono-xs text-secondary"
                  >
                    <span className="w-1 h-1 rounded-full bg-secondary" />
                    {tool.name}
                  </span>
                ))
              )}
            </div>
          </div>

          {/* Runs list (this session + active runs) */}
          <div className="mt-space-md px-space-md flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider mb-1">
              EJECUCIONES RECIENTES
            </span>
            {recentRuns.length === 0 ? (
              <span className="font-label-mono-xs text-label-mono-xs text-outline">
                {overviewLoading ? 'Cargando…' : 'Sin ejecuciones registradas.'}
              </span>
            ) : (
              recentRuns.map((entry) => (
                <button
                  key={entry.runId}
                  type="button"
                  onClick={() => setSelectedRunId(entry.runId)}
                  className={`p-space-sm rounded text-left flex flex-col gap-0.5 transition-colors ${
                    inspectedRun?.run_id === entry.runId
                      ? 'bg-surface-container-high'
                      : 'hover:bg-surface-container'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-body-sm text-body-sm text-on-surface truncate">
                      {entry.label}
                    </span>
                    <span
                      className={`font-label-mono-xs text-label-mono-xs whitespace-nowrap ${runTone(
                        entry.status,
                      )}`}
                    >
                      {entry.status}
                    </span>
                  </div>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    #{entry.runId.slice(0, 8)} · {entry.when}
                  </span>
                </button>
              ))
            )}
            <span className="font-label-mono-xs text-label-mono-xs text-outline-variant mt-1 leading-4">
              El backend solo expone las ejecuciones activas y las de esta sesión.
            </span>
          </div>
        </div>

        {/* Footer status */}
        <div className="p-space-md bg-surface-container-lowest">
          <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-tertiary' : 'bg-error'}`}
                />
                <span className="font-body-sm text-body-sm text-on-surface font-medium">
                  {connected ? 'Backend en línea' : 'Backend sin conexión'}
                </span>
              </div>
              <span className="material-symbols-outlined text-tertiary text-[16px]">shield</span>
            </div>
            <div className="flex items-center justify-between text-on-surface-variant">
              <span className="font-label-mono-xs text-label-mono-xs">Trust Engine</span>
              <span className="font-label-mono-xs text-label-mono-xs text-tertiary">
                {overview?.trust.default_decision ?? '--'}
              </span>
            </div>
          </div>
        </div>
      </aside>

      {/* Center Column: Conversation & Plan Canvas */}
      <main className="flex-1 flex flex-col justify-between bg-surface overflow-hidden min-w-0">
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-space-lg py-space-md flex flex-col gap-space-md"
        >
          {turns.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center gap-space-sm py-space-xl">
              <div className="w-12 h-12 rounded-xl bg-surface-container-high flex items-center justify-center text-primary">
                <span className="material-symbols-outlined text-[24px]">smart_toy</span>
              </div>
              <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                Objetivo Autónomo
              </span>
              <span className="font-body-sm text-body-sm text-on-surface-variant max-w-md">
                Describe un objetivo. El agente planificará los pasos, ejecutará las herramientas
                permitidas y te pedirá autorización para cualquier acción gobernada.
              </span>
              {!agentId && !overviewLoading && (
                <span className="font-label-mono-xs text-label-mono-xs text-error">
                  No hay un agente activo: crea o activa uno para poder ejecutar.
                </span>
              )}
            </div>
          ) : (
            turns.map((turn) => (
              <div key={turn.id} className="flex flex-col gap-space-md">
                {/* User intent */}
                <div className="flex items-start gap-space-md justify-end max-w-3xl ml-auto w-full">
                  <div className="bg-surface-container-high p-space-md rounded-xl max-w-xl min-w-0">
                    <div className="flex items-center justify-end gap-1.5 mb-1 text-on-surface-variant">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-secondary font-medium">
                        Operador Local
                      </span>
                      <span className="text-outline">·</span>
                      <span className="font-label-mono-xs text-label-mono-xs text-outline">
                        {clockTime(turn.createdAt)}
                      </span>
                    </div>
                    <p className="font-body-md text-body-md text-on-surface leading-relaxed whitespace-pre-wrap text-left">
                      {turn.prompt}
                    </p>
                  </div>
                  <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-on-primary font-body-sm text-body-sm font-semibold flex-shrink-0">
                    UL
                  </div>
                </div>

                {/* Agent run result */}
                <RunCard turn={turn} deciding={deciding} onDecide={decide} />
              </div>
            ))
          )}
        </div>

        {notice && (
          <div
            className={`mx-space-md mb-space-xs rounded p-space-sm flex items-center gap-space-xs font-body-sm text-body-sm ${
              notice.tone === 'ok'
                ? 'bg-tertiary/10 text-tertiary'
                : 'bg-error-container/30 text-error'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">
              {notice.tone === 'ok' ? 'check_circle' : 'error'}
            </span>
            <span>{notice.text}</span>
          </div>
        )}

        {/* Input bar */}
        <footer className="p-space-md bg-surface-container-low flex flex-col gap-space-xs">
          <div className="flex items-center gap-space-xs overflow-x-auto pb-1">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase mr-1">
              ACCESOS:
            </span>
            {QUICK_CHIPS.map((chip) => (
              <button
                key={chip}
                type="button"
                onClick={() => insertChip(chip)}
                className="px-2 py-0.5 rounded bg-surface-container font-label-mono-xs text-label-mono-xs text-secondary hover:bg-surface-container-high transition-colors whitespace-nowrap"
              >
                {chip}
              </button>
            ))}
          </div>

          <div className="bg-surface-container rounded-lg p-space-sm flex flex-col gap-space-xs">
            <textarea
              ref={inputRef}
              rows={2}
              value={input}
              disabled={sending}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  void send();
                }
              }}
              placeholder="Describe un objetivo o instrucción para el agente autónomo… (⌘/Ctrl + Enter para ejecutar)"
              className="bg-transparent text-on-surface font-body-md text-body-md placeholder:text-outline resize-none focus:outline-none w-full"
            />
            <div className="flex items-center justify-between pt-1 gap-space-sm">
              <div className="flex items-center gap-space-xs">
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-surface-container-high text-on-surface font-label-mono-xs text-label-mono-xs">
                  <span className="material-symbols-outlined text-secondary text-[14px]">
                    psychology
                  </span>
                  <span className="truncate max-w-[160px]">{model?.model ?? 'Modelo'}</span>
                </div>
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-surface-container-high text-tertiary font-label-mono-xs text-label-mono-xs">
                  <span className="material-symbols-outlined text-[14px]">construction</span>
                  <span>{toolItems.length} tools</span>
                </div>
              </div>
              <div className="flex items-center gap-space-sm">
                <span className="font-label-mono-xs text-label-mono-xs text-outline hidden md:inline">
                  ⌘ + Enter para ejecutar
                </span>
                <button
                  type="button"
                  disabled={sending || input.trim() === ''}
                  onClick={() => void send()}
                  className="px-space-md py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50 transition-all flex items-center gap-1"
                >
                  <span>{sending ? 'Ejecutando…' : 'Enviar'}</span>
                  <span className="material-symbols-outlined text-[16px]">send</span>
                </button>
              </div>
            </div>
          </div>
        </footer>
      </main>

      {/* Right Column: STDOUT & Live Telemetry Inspector */}
      <aside className="w-[320px] flex-shrink-0 bg-surface-container-lowest flex flex-col justify-between overflow-y-auto">
        <div className="flex flex-col">
          <div className="p-space-md bg-surface-container-low flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[18px]">terminal</span>
              <span className="font-headline-sm text-headline-sm text-on-surface font-semibold text-sm">
                Inspector STDOUT
              </span>
            </div>
            <span
              className={`font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded ${
                sending ? 'text-secondary bg-secondary/10' : 'text-outline bg-surface-container'
              }`}
            >
              {sending ? 'STREAMING' : 'IDLE'}
            </span>
          </div>

          <div className="p-space-sm bg-surface-container-low grid grid-cols-2 gap-space-xs">
            <div className="bg-surface-container p-2 rounded flex flex-col">
              <span className="font-label-mono-xs text-label-mono-xs text-outline">ACCIONES</span>
              <span className="font-label-mono-sm text-label-mono-sm text-tertiary font-bold">
                {inspectedActions.length}
              </span>
            </div>
            <div className="bg-surface-container p-2 rounded flex flex-col">
              <span className="font-label-mono-xs text-label-mono-xs text-outline">ESTADO</span>
              <span
                className={`font-label-mono-sm text-label-mono-sm font-bold ${
                  inspectedRun ? runTone(inspectedRun.status) : 'text-outline'
                }`}
              >
                {inspectedRun?.status ?? 'IDLE'}
              </span>
            </div>
          </div>

          <div className="p-space-md flex flex-col gap-2">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
              Grafo de Afinidad de Consulta
            </span>
            <div className="w-full bg-surface-container-low p-space-sm rounded">
              <span className="font-label-mono-xs text-label-mono-xs text-outline leading-5 block">
                El backend no expone recuperación vectorial ni similitud coseno por ejecución.
              </span>
            </div>
          </div>

          <div className="px-space-md flex flex-col gap-1 pb-space-md">
            <div className="flex items-center justify-between mb-1">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                REGISTROS CRONOMETRADOS
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-outline">
                {overview?.system.environment ?? '--'}
              </span>
            </div>
            {inspectedActions.length === 0 ? (
              <div className="font-code-base text-code-base text-[11px] text-outline bg-surface-container-low p-space-sm rounded">
                Sin acciones registradas para la ejecución seleccionada.
              </div>
            ) : (
              <div className="font-code-base text-code-base text-[11px] leading-relaxed flex flex-col gap-2 text-on-surface-variant bg-surface-container-low p-space-sm rounded">
                {inspectedActions.map((action, index) => (
                  <div key={`${index}-${action.tool_name}`}>
                    <span className="text-primary">[CALL]</span> {action.tool_name} →{' '}
                    <span className={stepTone(action.status)}>{action.status}</span>
                    <div className="text-on-surface-variant/80 pl-2">
                      <code>{summarize(action.arguments, 140)}</code>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-space-md bg-surface-container-low flex flex-col gap-space-xs">
          <div className="flex items-center justify-between">
            <span className="font-label-mono-xs text-label-mono-xs text-outline">
              RUNTIME: {runtime?.provider ?? '--'}
            </span>
            <span
              className={`font-label-mono-xs text-label-mono-xs ${
                runtime?.available ? 'text-secondary' : 'text-error'
              }`}
            >
              {runtime?.available ? 'DISPONIBLE' : 'NO DISPONIBLE'}
            </span>
          </div>
          <div className="flex items-center justify-between text-on-surface font-label-mono-xs text-label-mono-xs pt-1">
            <span className="truncate">{runtime?.detail || 'Sin detalle reportado por el runtime.'}</span>
          </div>
        </div>
      </aside>
    </div>
  );
}
