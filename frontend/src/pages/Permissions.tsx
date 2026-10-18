import { useEffect, useState, type FormEvent } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { useOverview } from '../hooks/useOverview';
import { permissionsApi } from '../services/api/permissionsApi';
import { ApiError } from '../services/api/apiClient';
import { EmptyRow, ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { OverviewAuthorization, Permission, PermissionDecision, RiskLevel } from '../types';

function riskText(risk: string): string {
  if (risk === 'HIGH') return 'text-error';
  if (risk === 'MEDIUM') return 'text-primary';
  return 'text-tertiary';
}

/** Live countdown over an ISO expiry, ticked once a second. */
function useCountdown(expiresAt: string) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const target = new Date(expiresAt).getTime();
  const remaining = Number.isFinite(target) ? Math.max(0, target - now) : 0;
  const minutes = String(Math.floor(remaining / 60000)).padStart(2, '0');
  const seconds = String(Math.floor((remaining % 60000) / 1000)).padStart(2, '0');
  return { expired: remaining <= 0, label: `${minutes}:${seconds}` };
}

interface PendingCardProps {
  request: OverviewAuthorization;
  busy: boolean;
  outcome: string | null;
  onDecide: (request: OverviewAuthorization, allow: boolean) => void;
}

function PendingCard({ request, busy, outcome, onDecide }: PendingCardProps) {
  const countdown = useCountdown(request.expires_at);

  return (
    <div className="bg-surface-container-low rounded-xl shadow-md overflow-hidden relative">
      <div className="bg-surface-container px-space-lg py-space-sm flex flex-wrap items-center justify-between gap-space-sm">
        <div className="flex items-center gap-space-sm min-w-0">
          <span className="w-2.5 h-2.5 rounded-full bg-secondary animate-ping" />
          <span className="font-code-base text-code-base font-semibold text-secondary truncate">
            {request.tool_name}
          </span>
        </div>
        <div className="flex items-center gap-space-xs">
          <span
            className={`font-label-mono-xs text-label-mono-xs px-space-xs py-0.5 rounded bg-error-container/40 font-medium uppercase tracking-wider ${riskText(
              request.risk_level,
            )}`}
          >
            {request.risk_level === 'HIGH' ? 'ALTO IMPACTO' : `RIESGO ${request.risk_level}`}
          </span>
          <span className="font-label-mono-xs text-label-mono-xs px-space-xs py-0.5 rounded bg-surface-container-highest text-on-surface-variant font-code-base">
            RUN {request.agent_run_id.slice(0, 8)}
          </span>
        </div>
      </div>

      <div className="p-space-lg flex flex-col gap-space-lg">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
          <div className="bg-surface-container rounded-lg p-space-sm flex flex-col gap-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Herramienta / Skill</span>
            <div className="flex items-center gap-1.5 text-on-surface">
              <span className="material-symbols-outlined text-secondary text-[16px]">terminal</span>
              <span className="font-code-base text-code-base font-medium truncate">{request.skill_name}</span>
            </div>
          </div>
          <div className="bg-surface-container rounded-lg p-space-sm flex flex-col gap-space-xs">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase">Solicitud</span>
            <div className="flex items-center gap-1.5 text-on-surface">
              <span className="material-symbols-outlined text-primary text-[16px]">account_tree</span>
              <span className="font-code-base text-code-base font-medium truncate">{request.request_id.slice(0, 8)}</span>
            </div>
          </div>
        </div>

        <div className="bg-surface-container-lowest rounded-lg p-space-md flex flex-col gap-space-xs">
          <div className="flex items-center justify-between">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider flex items-center gap-1">
              <span className="material-symbols-outlined text-[14px]">psychology</span>
              Razón expuesta por el agente
            </span>
          </div>
          <p className="font-body-md text-body-md text-on-surface italic bg-surface-container-low p-space-sm rounded">
            “{request.reason || 'El agente no adjuntó una razón.'}”
          </p>
        </div>

        <div className="bg-surface-container-high rounded-lg p-space-md flex flex-col gap-space-xs">
          <div className="flex items-center gap-space-xs">
            <span className="material-symbols-outlined text-secondary text-[18px]">gavel</span>
            <span className="font-label-mono-xs text-label-mono-xs text-secondary uppercase font-semibold">
              Disparador del Trust Engine
            </span>
          </div>
          <p className="font-body-sm text-body-sm text-on-surface">
            El Trust Engine clasificó esta acción como{' '}
            <span className="font-code-base text-code-base text-primary font-medium">
              {request.risk_level}
            </span>{' '}
            y la dejó en <span className="font-code-base text-code-base text-secondary">ASK</span>: requiere decisión humana
            antes de ejecutar.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row items-center justify-between gap-space-md pt-space-xs">
          <div className="flex items-center gap-space-xs bg-surface-container px-space-md py-space-xs rounded-lg">
            <span className="material-symbols-outlined text-secondary text-[18px] animate-spin">timelapse</span>
            <div className="flex items-center gap-1 font-label-mono-sm text-label-mono-sm text-on-surface">
              <span className="text-outline">Caducidad:</span>
              <span className="font-code-base text-secondary font-semibold">
                {countdown.expired ? 'Expirada' : `Expira en ${countdown.label}`}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-space-sm w-full sm:w-auto">
            <button
              type="button"
              disabled={busy || countdown.expired}
              onClick={() => onDecide(request, false)}
              className="flex-1 sm:flex-none px-space-lg py-space-sm bg-error-container hover:bg-error text-on-error-container hover:text-on-error disabled:opacity-50 rounded-lg font-body-sm text-body-sm font-semibold flex items-center justify-center gap-space-xs transition-colors shadow-sm"
            >
              <span className="material-symbols-outlined text-[18px]">block</span>
              <span>RECHAZAR</span>
            </button>
            <button
              type="button"
              disabled={busy || countdown.expired}
              onClick={() => onDecide(request, true)}
              className="flex-1 sm:flex-none px-space-xl py-space-sm bg-primary hover:bg-primary-container text-on-primary disabled:opacity-50 rounded-lg font-body-sm text-body-sm font-semibold flex items-center justify-center gap-space-xs transition-colors shadow-sm shadow-primary/20"
            >
              <span className="material-symbols-outlined text-[18px]">check</span>
              <span>APROBAR ACCIÓN</span>
            </button>
          </div>
        </div>

        {outcome && (
          <div className="p-space-sm rounded-lg bg-surface-container font-code-base text-label-mono-sm text-center">
            {outcome}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Permissions() {
  const grants = useAsyncData(() => permissionsApi.listPermissions(), []);
  const { data: overview, connected, refresh } = useOverview();
  const pending = overview?.authorizations.items ?? [];
  const pendingCount = overview?.authorizations.pending_count ?? pending.length;

  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, string>>({});
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);

  const [form, setForm] = useState<{
    skill_name: string;
    action_name: string;
    scope: string;
    effect: PermissionDecision;
    risk_level: RiskLevel;
  }>({ skill_name: '', action_name: '', scope: 'user', effect: 'ASK', risk_level: 'MEDIUM' });

  const trust = overview?.trust;
  const totalGrants = trust?.total_grants ?? 0;
  const pct = (value: number) => (totalGrants > 0 ? Math.round((value / totalGrants) * 100) : 0);

  const decide = async (request: OverviewAuthorization, allow: boolean) => {
    setBusy(request.request_id);
    setActionError(null);
    try {
      if (allow) await permissionsApi.approveRequest(request.agent_run_id, request.request_id);
      else await permissionsApi.rejectRequest(request.agent_run_id, request.request_id);
      setOutcomes((prev) => ({
        ...prev,
        [request.request_id]: allow
          ? 'Acción autorizada. El run se reanuda y vuelve a pasar por el Trust Engine.'
          : 'Solicitud denegada. El run observa el rechazo y puede continuar.',
      }));
      refresh();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : 'La decisión ha fallado.');
    } finally {
      setBusy(null);
    }
  };

  const revoke = async (permissionId: string) => {
    setBusy(permissionId);
    setActionError(null);
    try {
      await permissionsApi.deletePermission(permissionId);
      grants.reload();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : 'No se pudo revocar el permiso.');
    } finally {
      setBusy(null);
    }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    const agentId = overview?.agent?.id;
    if (!agentId) {
      setActionError('No hay un agente activo al que asociar la regla.');
      return;
    }
    setCreating(true);
    setActionError(null);
    try {
      await permissionsApi.createPermission({ agent_id: agentId, ...form });
      setForm((prev) => ({ ...prev, skill_name: '', action_name: '' }));
      setShowForm(false);
      grants.reload();
      refresh();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : 'No se pudo crear la regla.');
    } finally {
      setCreating(false);
    }
  };

  const grantList = grants.data ?? [];

  return (
    <div className="flex flex-col w-full">
      <div className="px-margin pt-space-lg pb-space-xl flex flex-col gap-space-lg max-w-[1720px] mx-auto w-full">
        {/* Hero */}
        <div className="relative bg-surface-container-low rounded-xl p-space-lg overflow-hidden shadow-sm">
          <div className="absolute -right-20 -top-24 w-96 h-96 rounded-full bg-primary/5 blur-3xl pointer-events-none" />
          <div className="absolute right-48 -bottom-16 w-64 h-64 rounded-full bg-secondary/5 blur-2xl pointer-events-none" />
          <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-space-md">
            <div className="flex flex-col gap-space-xs">
              <div className="flex flex-wrap items-center gap-space-sm">
                <span className="font-label-mono-xs text-label-mono-xs uppercase px-space-xs py-0.5 rounded bg-surface-container-highest text-secondary tracking-widest font-semibold">
                  ZERO-TRUST ARCHITECTURE
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-outline-variant">/</span>
                <span className="font-label-mono-xs text-label-mono-xs text-outline tracking-wider uppercase">
                  POL-SEC PROTOCOL
                </span>
              </div>
              <h1 className="font-headline-xl text-headline-xl text-on-surface tracking-tight font-semibold mt-1">
                Permisos y Aprobaciones
              </h1>
              <div className="flex flex-wrap items-center gap-space-md text-on-surface-variant font-label-mono-sm text-label-mono-sm mt-0.5">
                <span className={`flex items-center gap-1.5 ${connected ? 'text-tertiary' : 'text-error'}`}>
                  <span className={`w-2 h-2 rounded-full ${connected ? 'bg-tertiary animate-pulse' : 'bg-error'}`} />
                  Trust Engine {connected ? 'en línea' : 'sin conexión'}
                </span>
                <span className="text-outline-variant">•</span>
                <span className="text-on-surface">Modo {trust?.default_decision ?? '--'}</span>
                {overview?.agent && (
                  <>
                    <span className="text-outline-variant">•</span>
                    <span className="font-code-base text-secondary font-medium">
                      AGENT {overview.agent.id.slice(0, 8)}
                    </span>
                  </>
                )}
              </div>
            </div>

            <div className="flex items-center gap-space-sm self-start lg:self-center">
              <div className="px-space-md py-space-sm bg-surface-container rounded-lg flex items-center gap-space-sm shadow-sm">
                <span className="material-symbols-outlined text-secondary text-[20px]">verified_user</span>
                <div className="flex flex-col">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">REGLAS REGISTRADAS</span>
                  <span className="font-body-sm text-body-sm text-on-surface font-medium">
                    {grants.loading ? '…' : totalGrants} concesiones
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowForm((value) => !value)}
                disabled={!overview?.agent}
                className="bg-primary hover:bg-primary-container disabled:opacity-50 text-on-primary font-body-sm text-body-sm font-medium px-space-md py-space-sm rounded-lg flex items-center gap-space-xs transition-colors shadow-sm"
              >
                <span className="material-symbols-outlined text-[16px]">tune</span>
                <span>{showForm ? 'Cerrar' : 'Editar Reglas Base'}</span>
              </button>
            </div>
          </div>
        </div>

        {actionError && <ErrorRow message={actionError} />}

        {/* Decision KPIs */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter">
          <div className="bg-surface-container-low rounded-xl p-space-md shadow-sm relative overflow-hidden hover:bg-surface-container transition-colors">
            <div className="flex items-start justify-between">
              <div className="flex flex-col gap-space-xs">
                <span className="font-label-mono-xs text-label-mono-xs text-tertiary uppercase tracking-wider font-semibold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-tertiary" />
                  ALLOW · POLÍTICAS ACTIVAS
                </span>
                <div className="flex items-baseline gap-space-xs mt-1">
                  <span className="font-headline-xl text-headline-xl text-on-surface font-semibold tracking-tight">
                    {trust?.allow_grants ?? 0}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">reglas automáticas</span>
                </div>
                <p className="font-body-sm text-body-sm text-on-surface-variant mt-space-xs">
                  Acciones preautorizadas que se ejecutan sin intervención humana.
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-surface-container-high flex items-center justify-center text-tertiary">
                <span className="material-symbols-outlined text-[20px]">check_circle</span>
              </div>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full mt-space-md overflow-hidden">
              <div className="bg-tertiary h-full rounded-full" style={{ width: `${pct(trust?.allow_grants ?? 0)}%` }} />
            </div>
          </div>

          <div className="bg-surface-container rounded-xl p-space-md shadow-sm relative overflow-hidden">
            <div className="flex items-start justify-between">
              <div className="flex flex-col gap-space-xs">
                <span className="font-label-mono-xs text-label-mono-xs text-secondary uppercase tracking-wider font-semibold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-ping" />
                  ASK · COLA DE DECISIÓN
                </span>
                <div className="flex items-baseline gap-space-xs mt-1">
                  <span className="font-headline-xl text-headline-xl text-secondary font-semibold tracking-tight">
                    {pendingCount}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-secondary-fixed-dim">
                    solicitud{pendingCount === 1 ? '' : 'es'} pendiente{pendingCount === 1 ? '' : 's'}
                  </span>
                </div>
                <p className="font-body-sm text-body-sm text-on-surface-variant mt-space-xs">
                  Atención requerida: acciones que el Trust Engine derivó a aprobación humana.
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-surface-container-high flex items-center justify-center text-secondary">
                <span className="material-symbols-outlined text-[20px]">pending_actions</span>
              </div>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full mt-space-md overflow-hidden">
              <div
                className={`bg-secondary h-full rounded-full ${pendingCount > 0 ? 'animate-pulse w-full' : 'w-0'}`}
              />
            </div>
          </div>

          <div className="bg-surface-container-low rounded-xl p-space-md shadow-sm relative overflow-hidden hover:bg-surface-container transition-colors">
            <div className="flex items-start justify-between">
              <div className="flex flex-col gap-space-xs">
                <span className="font-label-mono-xs text-label-mono-xs text-error uppercase tracking-wider font-semibold flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-error" />
                  DENY · BLOQUEO PERMANENTE
                </span>
                <div className="flex items-baseline gap-space-xs mt-1">
                  <span className="font-headline-xl text-headline-xl text-on-surface font-semibold tracking-tight">
                    {trust?.deny_grants ?? 0}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">rutas restringidas</span>
                </div>
                <p className="font-body-sm text-body-sm text-on-surface-variant mt-space-xs">
                  Rutas vedadas explícitamente, sin posibilidad de aprobación interactiva.
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-surface-container-high flex items-center justify-center text-error">
                <span className="material-symbols-outlined text-[20px]">block</span>
              </div>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full mt-space-md overflow-hidden">
              <div className="bg-error h-full rounded-full" style={{ width: `${pct(trust?.deny_grants ?? 0)}%` }} />
            </div>
          </div>
        </div>

        {/* Create rule */}
        {showForm && (
          <div className="bg-surface-container-low rounded-xl p-space-md flex flex-col gap-space-sm shadow-sm">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                Nueva Regla Base
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">
                AGENT {overview?.agent ? overview.agent.id.slice(0, 8) : '—'}
              </span>
            </div>
            <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-space-sm items-end">
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">Skill</span>
                <input
                  required
                  value={form.skill_name}
                  onChange={(event) => setForm({ ...form, skill_name: event.target.value })}
                  placeholder="web_search"
                  className="bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-1 font-code-base text-code-base text-on-surface outline-none focus:border-primary"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">Acción</span>
                <input
                  required
                  value={form.action_name}
                  onChange={(event) => setForm({ ...form, action_name: event.target.value })}
                  placeholder="*"
                  className="bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-1 font-code-base text-code-base text-on-surface outline-none focus:border-primary"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">Scope</span>
                <input
                  required
                  value={form.scope}
                  onChange={(event) => setForm({ ...form, scope: event.target.value })}
                  className="bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-1 font-code-base text-code-base text-on-surface outline-none focus:border-primary"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">Efecto</span>
                <select
                  value={form.effect}
                  onChange={(event) => setForm({ ...form, effect: event.target.value as PermissionDecision })}
                  className="bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-1 font-code-base text-code-base text-on-surface outline-none focus:border-primary"
                >
                  <option value="ALLOW">ALLOW</option>
                  <option value="ASK">ASK</option>
                  <option value="DENY">DENY</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">Riesgo</span>
                <select
                  value={form.risk_level}
                  onChange={(event) => setForm({ ...form, risk_level: event.target.value as RiskLevel })}
                  className="bg-surface-container-lowest border border-outline-variant/40 rounded px-space-sm py-1 font-code-base text-code-base text-on-surface outline-none focus:border-primary"
                >
                  <option value="LOW">LOW</option>
                  <option value="MEDIUM">MEDIUM</option>
                  <option value="HIGH">HIGH</option>
                </select>
              </label>
              <button
                type="submit"
                disabled={creating}
                className="bg-primary text-on-primary hover:bg-primary-container disabled:opacity-50 rounded px-space-md py-1.5 font-body-sm text-body-sm font-medium transition-colors xl:col-span-5"
              >
                {creating ? 'Concediendo…' : 'Conceder Regla'}
              </button>
            </form>
            <span className="font-label-mono-xs text-label-mono-xs text-outline">
              El owner y el agente se resuelven en el servidor desde tu sesión.
            </span>
          </div>
        )}

        {/* Pending + matrices */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter items-start">
          <section className="lg:col-span-7 flex flex-col gap-space-md">
            <div className="flex items-center justify-between px-space-xs">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[18px]">radio_button_checked</span>
                <span className="font-label-mono-sm text-label-mono-sm text-on-surface font-semibold uppercase tracking-wider">
                  Solicitudes Pendientes ({pendingCount})
                </span>
              </div>
              <span className="font-label-mono-xs text-label-mono-xs text-outline">PRIORIDAD MÁXIMA</span>
            </div>

            {pending.length === 0 ? (
              <EmptyRow message="No hay autorizaciones pendientes en este momento." />
            ) : (
              pending.map((request) => (
                <PendingCard
                  key={request.request_id}
                  request={request}
                  busy={busy === request.request_id}
                  outcome={outcomes[request.request_id] ?? null}
                  onDecide={decide}
                />
              ))
            )}

            <div className="bg-surface-container-low rounded-xl p-space-md shadow-sm flex flex-col gap-space-sm">
              <div className="flex items-center justify-between">
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider font-semibold">
                  Topología de Impacto Previsto
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">NO EXPUESTO</span>
              </div>
              <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
                El backend no publica el diff previsto (archivos, servicio, reversibilidad) de cada
                solicitud. Solo expone la herramienta, el motivo y el nivel de riesgo.
              </p>
            </div>
          </section>

          <section className="lg:col-span-5 flex flex-col gap-space-lg">
            {/* Policy matrix */}
            <div className="bg-surface-container-low rounded-xl shadow-sm overflow-hidden flex flex-col">
              <div className="p-space-md bg-surface-container flex items-center justify-between">
                <div className="flex items-center gap-space-xs">
                  <span className="material-symbols-outlined text-primary text-[18px]">table_chart</span>
                  <span className="font-label-mono-sm text-label-mono-sm text-on-surface font-semibold uppercase tracking-wider">
                    Matriz de Políticas Activas
                  </span>
                </div>
                <div className="flex items-center gap-space-xs">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    {grantList.length} DEFINICIONES
                  </span>
                  <button
                    type="button"
                    onClick={grants.reload}
                    className="font-label-mono-xs text-label-mono-xs text-on-surface-variant hover:text-on-surface transition-colors flex items-center"
                  >
                    <span className="material-symbols-outlined text-[14px]">refresh</span>
                  </button>
                </div>
              </div>

              {grants.loading ? (
                <div className="p-space-md">
                  <LoadingRow label="Cargando políticas…" />
                </div>
              ) : grants.error ? (
                <div className="p-space-md">
                  <ErrorRow message={grants.error} onRetry={grants.reload} />
                </div>
              ) : grantList.length === 0 ? (
                <div className="p-space-md">
                  <EmptyRow message="Aún no hay reglas. Usa «Editar Reglas Base» para crear la primera." />
                </div>
              ) : (
                <div className="flex flex-col">
                  {grantList.map((permission: Permission) => (
                    <div
                      key={permission.id}
                      className="p-space-sm bg-surface-container-low flex items-center justify-between hover:bg-surface-container transition-colors group"
                    >
                      <div className="flex flex-col min-w-0 pr-2">
                        <span className="font-code-base text-code-base font-semibold text-on-surface truncate">
                          {permission.skill_name}.{permission.action_name}
                        </span>
                        <span className="font-body-sm text-body-sm text-on-surface-variant truncate">
                          scope {permission.scope} · riesgo {permission.risk_level}
                        </span>
                      </div>
                      <div className="flex items-center gap-space-xs shrink-0">
                        <span
                          className={`font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded font-semibold ${
                            permission.effect === 'ALLOW'
                              ? 'bg-tertiary/10 text-tertiary'
                              : permission.effect === 'DENY'
                                ? 'bg-error/10 text-error'
                                : 'bg-secondary/15 text-secondary'
                          }`}
                        >
                          {permission.effect}
                        </span>
                        <button
                          type="button"
                          disabled={busy === permission.id}
                          onClick={() => void revoke(permission.id)}
                          className="text-outline opacity-0 group-hover:opacity-100 hover:text-error disabled:opacity-50 transition-all"
                          title="Revocar"
                        >
                          <span className="material-symbols-outlined text-[16px]">delete</span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Audit trail (not exposed) */}
            <div className="bg-surface-container-low rounded-xl shadow-sm overflow-hidden flex flex-col">
              <div className="p-space-md bg-surface-container flex items-center justify-between">
                <div className="flex items-center gap-space-xs">
                  <span className="material-symbols-outlined text-secondary text-[18px]">history</span>
                  <span className="font-label-mono-sm text-label-mono-sm text-on-surface font-semibold uppercase tracking-wider">
                    Registro de Auditoría
                  </span>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">NO EXPUESTO</span>
              </div>
              <div className="p-space-md">
                <div className="bg-surface-container p-space-sm rounded-lg">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline leading-5 block">
                    El backend registra las decisiones de aprobación, pero no expone un endpoint de
                    lectura del audit trail. Las decisiones recientes quedan reflejadas en la cola de
                    solicitudes y en el estado de los runs.
                  </span>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
