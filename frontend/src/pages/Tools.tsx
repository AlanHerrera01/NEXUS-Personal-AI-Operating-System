import { useState } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { useOverview } from '../hooks/useOverview';
import { catalogApi } from '../services/api/catalogApi';
import { healthApi } from '../services/api/healthApi';
import { mcpApi } from '../services/api/mcpApi';
import { EmptyRow, ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { RegistrableTransport } from '../services/api/mcpApi';
import type { MCPServer, ToolView } from '../types';

/** Best-effort icon per tool, purely cosmetic and derived from the real name. */
function toolIcon(tool: ToolView): string {
  const key = `${tool.name} ${tool.skill} ${tool.category ?? ''}`.toLowerCase();
  if (key.includes('search') || key.includes('web') || key.includes('browse')) return 'travel_explore';
  if (key.includes('memory') || key.includes('sql') || key.includes('db') || key.includes('database')) return 'database';
  if (key.includes('shell') || key.includes('terminal') || key.includes('bash') || key.includes('exec')) return 'terminal';
  if (key.includes('calendar') || key.includes('schedule') || key.includes('time')) return 'calendar_month';
  if (key.includes('git') || key.includes('repo') || key.includes('code')) return 'code_blocks';
  if (key.includes('file') || key.includes('read') || key.includes('write') || key.includes('doc')) return 'description';
  return 'handyman';
}

function riskBadge(risk: string): string {
  if (risk === 'HIGH') return 'bg-error-container/30 text-error';
  if (risk === 'MEDIUM') return 'bg-primary/10 text-primary';
  return 'bg-tertiary-container/15 text-tertiary';
}

/** The declared parameter names of a tool's JSON schema, if any. */
function schemaProperties(schema: Record<string, unknown> | undefined): string[] {
  const properties = schema?.properties;
  if (properties && typeof properties === 'object') {
    return Object.keys(properties as Record<string, unknown>);
  }
  return [];
}

const TRANSPORT_LABELS: Record<string, string> = {
  stdio: 'STDIO',
  sse: 'SSE',
  streamable_http: 'HTTP',
};

type MCPServerForm = {
  name: string;
  description: string;
  transport: RegistrableTransport;
  /** stdio: the whole command line. sse/streamable_http: the URL. */
  command: string;
  envText: string;
  headersText: string;
};

const EMPTY_FORM: MCPServerForm = {
  name: '',
  description: '',
  transport: 'stdio',
  command: '',
  envText: '',
  headersText: '',
};

/** Parse "KEY=value" lines into an object; null when nothing usable is present. */
function parseKeyValues(text: string): Record<string, string> | null {
  const result: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const entry = line.trim();
    if (!entry) continue;
    const at = entry.indexOf('=');
    if (at <= 0) continue;
    result[entry.slice(0, at).trim()] = entry.slice(at + 1).trim();
  }
  return Object.keys(result).length > 0 ? result : null;
}

export default function Tools() {
  const tools = useAsyncData(() => catalogApi.listTools(), []);
  const skills = useAsyncData(() => catalogApi.listSkills(), []);
  const runtime = useAsyncData(() => healthApi.runtime(), []);
  const servers = useAsyncData(() => mcpApi.list(), []);
  const { data: overview, connected } = useOverview();

  const [skillFilter, setSkillFilter] = useState<string>('ALL');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<ToolView | null>(null);
  const [showConnect, setShowConnect] = useState(false);
  const [form, setForm] = useState<MCPServerForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyServer, setBusyServer] = useState<string | null>(null);

  const toolList = tools.data ?? [];
  const skillList = skills.data ?? [];
  const serverList = servers.data?.items ?? [];
  // The registrable transports come from the backend rather than a hardcoded
  // menu, so the dialog cannot offer one the API would reject.
  const transportOptions: RegistrableTransport[] = (servers.data
    ?.transports as RegistrableTransport[] | undefined) ?? [
    'stdio',
    'sse',
    'streamable_http',
  ];

  const visible = toolList.filter((tool) => {
    if (skillFilter !== 'ALL' && tool.skill !== skillFilter) return false;
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return `${tool.name} ${tool.skill} ${tool.description} ${tool.category ?? ''}`
      .toLowerCase()
      .includes(needle);
  });

  const readOnlyCount = toolList.filter((tool) => tool.read_only).length;
  const confirmCount = toolList.filter((tool) => tool.requires_confirmation).length;

  const countFor = (skill: string) => toolList.filter((tool) => tool.skill === skill).length;

  const reloadAll = () => {
    tools.reload();
    skills.reload();
    runtime.reload();
    servers.reload();
  };

  /** Register configuration only; the backend opens no connection here. */
  const submitServer = async () => {
    const name = form.name.trim();
    const description = form.description.trim();
    const command = form.command.trim();
    if (!name || !description || !command) {
      setFormError('Nombre, descripción y comando/URL son obligatorios.');
      return;
    }

    const configuration: Record<string, unknown> = {};
    let endpoint = command;
    if (form.transport === 'stdio') {
      // The adapter reads configuration.command as an argv list.
      const argv = command.split(/\s+/).filter(Boolean);
      endpoint = argv[0];
      configuration.command = argv;
      const env = parseKeyValues(form.envText);
      if (env) configuration.env = env;
    } else {
      const headers = parseKeyValues(form.headersText);
      if (headers) configuration.headers = headers;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      await mcpApi.register({
        name,
        description,
        transport_type: form.transport,
        endpoint,
        configuration,
      });
      setForm(EMPTY_FORM);
      servers.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'No se pudo registrar el servidor.');
    } finally {
      setSubmitting(false);
    }
  };

  const toggleServer = async (server: MCPServer) => {
    setBusyServer(server.id);
    setFormError(null);
    try {
      await mcpApi.update(server.id, { enabled: !server.enabled });
      servers.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'No se pudo actualizar el servidor.');
    } finally {
      setBusyServer(null);
    }
  };

  const removeServer = async (server: MCPServer) => {
    setBusyServer(server.id);
    setFormError(null);
    try {
      await mcpApi.remove(server.id);
      servers.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'No se pudo eliminar el servidor.');
    } finally {
      setBusyServer(null);
    }
  };

  const filters: { key: string; label: string; count: number }[] = [
    { key: 'ALL', label: 'Todas', count: toolList.length },
    ...skillList.map((skill) => ({ key: skill.name, label: skill.name, count: countFor(skill.name) })),
  ];

  return (
    <div className="flex flex-col w-full pb-margin">
      {/* Header + filter ribbon */}
      <div className="relative py-space-lg mb-space-lg flex flex-col gap-space-md">
        <div className="absolute -top-10 left-1/4 w-96 h-32 bg-primary/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-4 right-10 w-64 h-32 bg-secondary/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative flex flex-col md:flex-row md:items-end justify-between gap-space-md">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs uppercase text-secondary">
              <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
              <span>NEXUS Runtime Architecture</span>
              <span className="text-outline">/</span>
              <span className="text-on-surface-variant">EXTENSIONS &amp; SANDBOX</span>
            </div>
            <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight">
              Herramientas e Integraciones
            </h1>
            <p className="font-body-md text-body-md text-on-surface-variant max-w-2xl">
              Capacidades conectadas, aislamiento de ejecución y control de acceso determinista sobre
              el catálogo real de herramientas y skills del backend.
            </p>
          </div>
          <div className="flex items-center gap-space-sm self-start md:self-auto">
            <button
              type="button"
              onClick={reloadAll}
              className="flex items-center gap-2 px-space-md py-2 rounded-lg bg-surface-container-low hover:bg-surface-container text-on-surface-variant hover:text-on-surface font-body-sm text-body-sm transition-colors"
            >
              <span className="material-symbols-outlined text-[18px]">refresh</span>
              <span>Recargar</span>
            </button>
            <button
              type="button"
              onClick={() => setShowConnect(true)}
              className="flex items-center gap-2 px-space-md py-2 rounded-lg bg-primary-container text-on-primary font-body-sm text-body-sm font-semibold shadow-md hover:bg-primary transition-all duration-150 active:scale-95"
            >
              <span className="material-symbols-outlined text-[18px]">add_circle</span>
              <span>Añadir Conexión MCP</span>
              {serverList.length > 0 && (
                <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-on-primary/20">
                  {serverList.length}
                </span>
              )}
            </button>
          </div>
        </div>

        <div className="mt-space-sm p-space-md rounded-xl bg-surface-container-low flex flex-col xl:flex-row xl:items-center justify-between gap-space-md shadow-sm">
          <div className="flex flex-wrap items-center gap-space-xs">
            {filters.map((filter) => (
              <button
                key={filter.key}
                type="button"
                onClick={() => setSkillFilter(filter.key)}
                className={`px-3 py-1.5 rounded-lg font-body-sm text-body-sm flex items-center transition-colors ${
                  skillFilter === filter.key
                    ? 'bg-surface-container-high text-on-surface font-medium shadow-sm'
                    : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
                }`}
              >
                {filter.label}
                <span className="ml-1 font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-highest text-secondary">
                  {filter.count}
                </span>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-space-lg flex-wrap font-label-mono-xs text-label-mono-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${connected ? 'bg-tertiary' : 'bg-error'}`} />
              <span className="text-on-surface font-medium">{toolList.length} Herramientas</span>
            </div>
            <span className="text-outline-variant">·</span>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-secondary" />
              <span className="text-on-surface-variant">{skillList.length} Skills</span>
            </div>
            <span className="text-outline-variant">·</span>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-outline" />
              <span className="text-outline">{readOnlyCount} Solo lectura</span>
            </div>
            <span className="text-outline-variant">·</span>
            <div className="flex items-center gap-1.5 text-primary">
              <span className="material-symbols-outlined text-[14px]">shield_lock</span>
              <span>{confirmCount} Con confirmación</span>
            </div>
          </div>
        </div>
      </div>

      {/* Search + runtime context */}
      <div className="mb-space-lg grid grid-cols-1 md:grid-cols-12 gap-gutter">
        <div className="md:col-span-8 flex items-center gap-space-sm bg-surface-container-lowest px-space-md py-2.5 rounded-xl shadow-sm focus-within:ring-1 focus-within:ring-primary/40 transition-all">
          <span className="material-symbols-outlined text-outline text-[18px]">search</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="w-full bg-transparent text-on-surface placeholder:text-outline font-body-md text-body-md outline-none"
            placeholder="Buscar herramientas, capacidades, skills y categorías…"
          />
          <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant">
            FILTER
          </span>
        </div>
        <div className="md:col-span-4 bg-surface-container-low px-space-md py-2 rounded-xl flex items-center justify-between shadow-sm">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary text-[18px]">memory</span>
            <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant uppercase tracking-wider">
              Runtime Sandbox
            </span>
          </div>
          <div className="flex items-center gap-1.5 font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-highest text-secondary">
            <span className="font-mono">{runtime.data?.provider ?? '--'}</span>
            <span className="text-outline">/</span>
            <span className={runtime.data?.available ? 'text-tertiary' : 'text-error'}>
              {runtime.data?.available ? 'DISPONIBLE' : 'NO DISPONIBLE'}
            </span>
          </div>
        </div>
      </div>

      {/* Tool grid */}
      {tools.loading ? (
        <LoadingRow label="Cargando catálogo de herramientas…" />
      ) : tools.error ? (
        <ErrorRow message={tools.error} onRetry={tools.reload} />
      ) : toolList.length === 0 ? (
        <EmptyRow message="El backend no tiene herramientas registradas." />
      ) : visible.length === 0 ? (
        <EmptyRow message="Ninguna herramienta coincide con el filtro o la búsqueda." />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-gutter items-stretch">
          {visible.map((tool) => {
            const params = schemaProperties(tool.input_schema);
            return (
              <div
                key={tool.name}
                className="group rounded-xl bg-surface-container-low p-space-lg flex flex-col justify-between shadow-md hover:bg-surface-container transition-all duration-200"
              >
                <div className="flex flex-col">
                  <div className="flex items-start justify-between gap-2 pb-space-md">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center text-on-surface shadow-sm shrink-0">
                        <span className="material-symbols-outlined text-[22px] text-secondary">
                          {toolIcon(tool)}
                        </span>
                      </div>
                      <div className="flex flex-col min-w-0">
                        <span className="font-headline-sm text-headline-sm font-semibold text-on-surface truncate">
                          {tool.name}
                        </span>
                        <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                          {tool.skill} · v{tool.version}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-container-highest font-label-mono-xs text-label-mono-xs font-semibold shrink-0">
                      <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
                      <span className={riskBadge(tool.risk_level).split(' ')[1]}>{tool.risk_level}</span>
                    </div>
                  </div>

                  <p className="font-body-sm text-body-sm text-on-surface-variant mt-1 line-clamp-3">
                    {tool.description}
                  </p>

                  <div className="mt-space-md pt-space-sm flex flex-col gap-1.5">
                    <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                      Declaración de ejecución
                    </span>
                    <div className="flex flex-wrap gap-1.5 font-label-mono-xs text-label-mono-xs">
                      {tool.read_only && (
                        <span className="px-2 py-0.5 rounded bg-tertiary-container/15 text-tertiary font-medium">
                          Solo lectura
                        </span>
                      )}
                      {tool.side_effect && (
                        <span className="px-2 py-0.5 rounded bg-secondary-container/20 text-secondary font-medium">
                          Efecto secundario
                        </span>
                      )}
                      {tool.requires_confirmation && (
                        <span className="px-2 py-0.5 rounded bg-primary/10 text-primary font-medium">
                          Requiere confirmación
                        </span>
                      )}
                      <span className={`px-2 py-0.5 rounded font-medium ${riskBadge(tool.risk_level)}`}>
                        Riesgo {tool.risk_level}
                      </span>
                    </div>
                  </div>

                  <div className="mt-space-md">
                    <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                      Parámetros expuestos
                    </span>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {params.length === 0 ? (
                        <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container text-outline">
                          sin parámetros declarados
                        </span>
                      ) : (
                        <>
                          {params.slice(0, 6).map((param) => (
                            <span
                              key={param}
                              className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container text-on-surface-variant"
                            >
                              {param}
                            </span>
                          ))}
                          {params.length > 6 && (
                            <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container text-outline">
                              +{params.length - 6}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </div>

                  <div className="mt-space-md p-space-sm rounded-lg bg-surface-container-lowest flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-outline text-[16px]">history</span>
                      <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                        Sin telemetría de ejecución
                      </span>
                    </div>
                    <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">
                      NO EXPUESTO
                    </span>
                  </div>
                </div>

                <div className="mt-space-lg pt-space-sm flex items-center justify-between gap-space-sm">
                  <button
                    type="button"
                    onClick={() => setSelected(tool)}
                    className="px-3 py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-bright text-on-surface font-body-sm text-body-sm transition-colors flex items-center gap-1"
                  >
                    <span className="material-symbols-outlined text-[15px]">tune</span>
                    <span>Ver esquema</span>
                  </button>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono truncate">
                    {tool.category ?? 'sin categoría'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* MCP protocol health */}
      <div className="mt-margin p-space-lg rounded-xl bg-surface-container-low shadow-lg flex flex-col gap-space-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between pb-space-sm gap-space-sm">
          <div className="flex items-center gap-space-sm">
            <div className="w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center">
              <span className="material-symbols-outlined text-secondary text-[20px]">hub</span>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                  Estado del Runtime y del Catálogo
                </span>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-high text-secondary">
                  {overview?.model.provider ?? '--'}
                </span>
              </div>
              <span className="font-body-sm text-body-sm text-on-surface-variant">
                Estado real del sandbox de ejecución y del catálogo expuesto por el backend.
              </span>
            </div>
          </div>
          <div
            className={`flex items-center gap-2 font-label-mono-xs text-label-mono-xs px-3 py-1.5 rounded-lg shadow-sm ${
              runtime.data?.available
                ? 'text-tertiary bg-surface-container-lowest'
                : 'text-error bg-surface-container-lowest'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${runtime.data?.available ? 'bg-tertiary' : 'bg-error'}`} />
            <span>{runtime.data?.available ? 'RUNTIME DISPONIBLE' : 'RUNTIME NO DISPONIBLE'}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-gutter pt-space-sm">
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              Proveedor Sandbox
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {runtime.data?.provider ?? '--'}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant font-mono truncate">
              {runtime.data?.detail || 'sin detalle'}
            </span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              Versión Runtime
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {runtime.data?.version ?? '--'}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">Provider reportado</span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              Herramientas / Skills
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {toolList.length} / {skillList.length}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">Catálogo del backend</span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              Modelo de Inferencia
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold truncate">
              {overview?.model.model ?? '--'}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              {overview?.model.configured ? 'Configurado' : 'No configurado'}
            </span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              Servidores MCP
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {serverList.length}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              Registrados (configuración)
            </span>
          </div>
        </div>

        <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
          El backend no expone métricas de transporte MCP (canales, latencia, invocaciones): este
          panel muestra el catálogo, el runtime y los servidores MCP que registres. Registrar guarda
          configuración, no conecta: no se lanza ningún proceso y el registro aún no está enganchado
          al pipeline de herramientas.
        </p>
      </div>

      {/* Tool schema modal */}
      {selected && (
        <div
          className="fixed inset-0 z-50 bg-surface-container-lowest/80 backdrop-blur-md flex items-center justify-center p-space-md"
          onClick={() => setSelected(null)}
        >
          <div
            className="relative w-full max-w-2xl rounded-xl bg-surface-container-low shadow-2xl p-space-lg flex flex-col gap-space-md max-h-[85vh] overflow-y-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-space-sm">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center text-secondary shrink-0">
                  <span className="material-symbols-outlined text-[20px]">{toolIcon(selected)}</span>
                </div>
                <div className="min-w-0">
                  <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold truncate">
                    {selected.name}
                  </h2>
                  <p className="font-body-sm text-body-sm text-on-surface-variant truncate">
                    {selected.skill} · v{selected.version} · {selected.category ?? 'sin categoría'}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="p-1 rounded text-outline hover:text-on-surface hover:bg-surface-container transition-colors"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>

            <div className="flex flex-wrap gap-1.5 font-label-mono-xs text-label-mono-xs">
              {selected.read_only && (
                <span className="px-2 py-0.5 rounded bg-tertiary-container/15 text-tertiary font-medium">
                  Solo lectura
                </span>
              )}
              {selected.side_effect && (
                <span className="px-2 py-0.5 rounded bg-secondary-container/20 text-secondary font-medium">
                  Efecto secundario
                </span>
              )}
              {selected.requires_confirmation && (
                <span className="px-2 py-0.5 rounded bg-primary/10 text-primary font-medium">
                  Requiere confirmación
                </span>
              )}
              <span className={`px-2 py-0.5 rounded font-medium ${riskBadge(selected.risk_level)}`}>
                Riesgo {selected.risk_level}
              </span>
            </div>

            <p className="font-body-md text-body-md text-on-surface-variant">{selected.description}</p>

            <div className="flex flex-col gap-1">
              <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                input_schema
              </span>
              <pre className="bg-surface-container-lowest rounded-lg p-space-md font-code-base text-code-base text-on-surface overflow-x-auto whitespace-pre">
                {JSON.stringify(selected.input_schema, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* MCP server registration. The backend stores configuration and never
          connects here; connecting happens in the orchestrator under the Trust
          Engine, and this dialog says so out loud rather than implying more. */}
      {showConnect && (
        <div
          className="fixed inset-0 z-50 bg-surface-container-lowest/80 backdrop-blur-md flex items-center justify-center p-space-md"
          onClick={() => setShowConnect(false)}
        >
          <div
            className="relative w-full max-w-2xl max-h-[88vh] overflow-y-auto rounded-xl bg-surface-container-low shadow-2xl p-space-lg flex flex-col gap-space-md"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-space-sm">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-primary-container/20 flex items-center justify-center text-primary">
                  <span className="material-symbols-outlined text-[20px]">add_link</span>
                </div>
                <div>
                  <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                    Conectar Nuevo Servidor MCP
                  </h2>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">
                    Registro de servidores MCP locales o remotos.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowConnect(false)}
                className="p-1 rounded text-outline hover:text-on-surface hover:bg-surface-container transition-colors"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>

            <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-space-xs">
              <div className="flex items-center gap-2 text-secondary">
                <span className="material-symbols-outlined text-[18px]">info</span>
                <span className="font-label-mono-xs text-label-mono-xs uppercase tracking-wider font-semibold">
                  Registro, no conexión
                </span>
              </div>
              <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                Registrar guarda la configuración del servidor: no se lanza ningún proceso ni se abre
                ninguna conexión. Y todavía nada la consume: el adaptador MCP existe, pero aún no está
                enganchado al pipeline de herramientas del orquestador.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-space-sm">
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                  Nombre
                </span>
                <input
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  placeholder="filesystem"
                  className="bg-surface-container-lowest rounded-lg px-space-sm py-2 font-body-sm text-body-sm text-on-surface placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/40"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                  Descripción
                </span>
                <input
                  value={form.description}
                  onChange={(event) => setForm({ ...form, description: event.target.value })}
                  placeholder="Acceso de solo lectura a un directorio"
                  className="bg-surface-container-lowest rounded-lg px-space-sm py-2 font-body-sm text-body-sm text-on-surface placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/40"
                />
              </label>
            </div>

            <div className="flex flex-col gap-1">
              <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                Transporte
              </span>
              <div className="flex flex-wrap gap-1.5">
                {transportOptions.map((transport) => (
                  <button
                    key={transport}
                    type="button"
                    onClick={() => setForm({ ...form, transport })}
                    className={`px-3 py-1.5 rounded-lg font-label-mono-xs text-label-mono-xs transition-colors ${
                      form.transport === transport
                        ? 'bg-surface-container-high text-on-surface font-medium shadow-sm'
                        : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
                    }`}
                  >
                    {TRANSPORT_LABELS[transport]}
                  </button>
                ))}
              </div>
            </div>

            <label className="flex flex-col gap-1">
              <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                {form.transport === 'stdio' ? 'Comando (con argumentos)' : 'URL del endpoint'}
              </span>
              <input
                value={form.command}
                onChange={(event) => setForm({ ...form, command: event.target.value })}
                placeholder={
                  form.transport === 'stdio'
                    ? 'npx -y @modelcontextprotocol/server-filesystem /tmp'
                    : 'https://example.invalid/mcp'
                }
                className="bg-surface-container-lowest rounded-lg px-space-sm py-2 font-code-base text-code-base text-on-surface placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/40"
              />
            </label>

            {form.transport === 'stdio' ? (
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                  Variables de entorno (KEY=valor, una por línea)
                </span>
                <textarea
                  value={form.envText}
                  onChange={(event) => setForm({ ...form, envText: event.target.value })}
                  rows={3}
                  className="bg-surface-container-lowest rounded-lg px-space-sm py-2 font-code-base text-code-base text-on-surface placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/40 resize-y"
                />
              </label>
            ) : (
              <label className="flex flex-col gap-1">
                <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                  Cabeceras (KEY=valor, una por línea)
                </span>
                <textarea
                  value={form.headersText}
                  onChange={(event) => setForm({ ...form, headersText: event.target.value })}
                  rows={3}
                  className="bg-surface-container-lowest rounded-lg px-space-sm py-2 font-code-base text-code-base text-on-surface placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/40 resize-y"
                />
              </label>
            )}

            {formError && (
              <p className="font-body-sm text-body-sm text-error" role="alert">
                {formError}
              </p>
            )}

            <div className="flex items-center justify-between gap-space-sm">
              <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
                {form.transport === 'sse'
                  ? 'SSE se registra, pero el adaptador actual todavía no lo implementa.'
                  : 'Se guarda la configuración; todavía nada la conecta.'}
              </p>
              <button
                type="button"
                onClick={submitServer}
                disabled={submitting}
                className="shrink-0 px-4 py-2 rounded-lg bg-primary-container text-on-primary font-body-sm text-body-sm font-semibold shadow-md hover:bg-primary transition-all duration-150 active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {submitting ? 'Registrando…' : 'Registrar servidor'}
              </button>
            </div>

            <div className="flex flex-col gap-space-xs pt-space-sm">
              <div className="flex items-center justify-between">
                <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                  Servidores registrados
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-secondary">
                  {servers.data?.registered ?? 0}
                </span>
              </div>

              {servers.loading ? (
                <p className="font-body-sm text-body-sm text-on-surface-variant">Cargando…</p>
              ) : servers.error ? (
                <p className="font-body-sm text-body-sm text-error">{servers.error}</p>
              ) : serverList.length === 0 ? (
                <p className="font-body-sm text-body-sm text-outline">
                  Todavía no hay servidores MCP registrados.
                </p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {serverList.map((server) => (
                    <li
                      key={server.id}
                      className="p-space-sm rounded-lg bg-surface-container-lowest flex items-center justify-between gap-space-sm"
                    >
                      <div className="flex flex-col min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-body-sm text-body-sm font-semibold text-on-surface truncate">
                            {server.name}
                          </span>
                          <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-high text-secondary">
                            {TRANSPORT_LABELS[server.transport_type] ?? server.transport_type}
                          </span>
                          {!server.transport_supported && (
                            <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-error-container/30 text-error">
                              sin adaptador
                            </span>
                          )}
                          {!server.enabled && (
                            <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container text-outline">
                              deshabilitado
                            </span>
                          )}
                        </div>
                        <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono truncate">
                          {server.endpoint}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          onClick={() => toggleServer(server)}
                          disabled={busyServer === server.id}
                          className="px-2.5 py-1 rounded-lg bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-mono-xs text-label-mono-xs transition-colors disabled:opacity-60"
                        >
                          {server.enabled ? 'Deshabilitar' : 'Habilitar'}
                        </button>
                        <button
                          type="button"
                          onClick={() => removeServer(server)}
                          disabled={busyServer === server.id}
                          className="px-2.5 py-1 rounded-lg bg-error-container/30 hover:bg-error-container/50 text-error font-label-mono-xs text-label-mono-xs transition-colors disabled:opacity-60"
                        >
                          Eliminar
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
