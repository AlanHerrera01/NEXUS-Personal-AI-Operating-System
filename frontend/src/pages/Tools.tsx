import { useState } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { useI18n } from '../hooks/useI18n';
import { useOverview } from '../hooks/useOverview';
import { catalogApi } from '../services/api/catalogApi';
import { healthApi } from '../services/api/healthApi';
import { mcpApi } from '../services/api/mcpApi';
import { EmptyRow, ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { RegistrableTransport } from '../services/api/mcpApi';
import type { MCPConnectionTest, MCPServer, ToolView } from '../types';

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

const TRANSPORT_ICONS: Record<string, string> = {
  stdio: 'terminal',
  sse: 'rss_feed',
  streamable_http: 'http',
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
  transport: 'streamable_http',
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
  const { t } = useI18n();
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
  const [formNotice, setFormNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyServer, setBusyServer] = useState<string | null>(null);
  const [testingServer, setTestingServer] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, MCPConnectionTest>>({});

  const toolList = tools.data ?? [];
  const skillList = skills.data ?? [];
  const serverList = servers.data?.items ?? [];
  const enabledServers = serverList.filter((server) => server.enabled).length;
  const supportedServers = serverList.filter((server) => server.transport_supported).length;
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

  /** Open a real connection and keep the result next to the row. */
  const testServer = async (server: MCPServer, announce = false): Promise<MCPConnectionTest | null> => {
    setTestingServer(server.id);
    setFormError(null);
    setFormNotice(null);
    try {
      const result = await mcpApi.test(server.id);
      setTestResults((current) => ({ ...current, [server.id]: result }));
      servers.reload();
      if (announce) {
        if (result.ok) {
          setFormNotice(
            t('pages.tools.connect.connected', { count: result.tool_count, name: server.name }),
          );
        } else {
          setFormError(
            t('pages.tools.connect.testFailed', {
              error: result.error ?? t('pages.tools.connect.unknownError'),
            }),
          );
        }
      }
      return result;
    } catch (error) {
      setFormError(
        error instanceof Error ? error.message : t('pages.tools.connect.errors.test'),
      );
      return null;
    } finally {
      setTestingServer(null);
    }
  };

  /** Register configuration, then test a remote server immediately. */
  const submitServer = async () => {
    const name = form.name.trim();
    const description = form.description.trim();
    const command = form.command.trim();
    if (!name || !description || !command) {
      setFormError(t('pages.tools.connect.errors.required'));
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
    setFormNotice(null);
    let created: MCPServer;
    try {
      created = await mcpApi.register({
        name,
        description,
        transport_type: form.transport,
        endpoint,
        configuration,
      });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : t('pages.tools.connect.errors.register'));
      return;
    } finally {
      setSubmitting(false);
    }

    setForm(EMPTY_FORM);
    servers.reload();

    if (created.transport_type === 'stdio') {
      setFormNotice(t('pages.tools.connect.stdioRegistered'));
      return;
    }
    await testServer(created, true);
  };

  const toggleServer = async (server: MCPServer) => {
    setBusyServer(server.id);
    setFormError(null);
    try {
      await mcpApi.update(server.id, { enabled: !server.enabled });
      servers.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : t('pages.tools.connect.errors.update'));
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
      setFormError(error instanceof Error ? error.message : t('pages.tools.connect.errors.remove'));
    } finally {
      setBusyServer(null);
    }
  };

  const filters: { key: string; label: string; count: number }[] = [
    { key: 'ALL', label: t('pages.tools.filters.all'), count: toolList.length },
    ...skillList.map((skill) => ({ key: skill.name, label: skill.name, count: countFor(skill.name) })),
  ];

  const serverStatusLabel = (status: MCPServer['status']) => {
    switch (status) {
      case 'READY':
        return t('pages.tools.connect.status.ready');
      case 'CONNECTING':
        return t('pages.tools.connect.status.connecting');
      case 'ERROR':
        return t('pages.tools.connect.status.error');
      case 'DISABLED':
        return t('pages.tools.connect.status.disabled');
      default:
        return t('pages.tools.connect.status.disconnected');
    }
  };

  const statusDot = (server: MCPServer) => {
    if (!server.enabled || server.status === 'DISABLED') return 'bg-outline';
    if (server.status === 'READY') return 'bg-tertiary';
    if (server.status === 'ERROR') return 'bg-error';
    if (server.status === 'CONNECTING') return 'bg-secondary animate-pulse';
    return 'bg-outline';
  };

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
              <span>{t('pages.tools.header.breadcrumb')}</span>
              <span className="text-outline">/</span>
              <span className="text-on-surface-variant">{t('pages.tools.header.scope')}</span>
            </div>
            <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight">
              {t('pages.tools.header.title')}
            </h1>
            <p className="font-body-md text-body-md text-on-surface-variant max-w-2xl">
              {t('pages.tools.header.description')}
            </p>
          </div>
          <div className="flex items-center gap-space-sm self-start md:self-auto">
            <button
              type="button"
              onClick={reloadAll}
              className="flex items-center gap-2 px-space-md py-2 rounded-lg bg-surface-container-low hover:bg-surface-container text-on-surface-variant hover:text-on-surface font-body-sm text-body-sm transition-colors"
            >
              <span className="material-symbols-outlined text-[18px]">refresh</span>
              <span>{t('common.reload')}</span>
            </button>
            <button
              type="button"
              onClick={() => setShowConnect(true)}
              className="flex items-center gap-2 px-space-md py-2 rounded-lg bg-primary-container text-on-primary font-body-sm text-body-sm font-semibold shadow-md hover:bg-primary transition-all duration-150 active:scale-95"
            >
              <span className="material-symbols-outlined text-[18px]">add_circle</span>
              <span>{t('pages.tools.header.addConnection')}</span>
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
              <span className="text-on-surface font-medium">{t('pages.tools.stats.tools', { count: toolList.length })}</span>
            </div>
            <span className="text-outline-variant">·</span>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-secondary" />
              <span className="text-on-surface-variant">{t('pages.tools.stats.skills', { count: skillList.length })}</span>
            </div>
            <span className="text-outline-variant">·</span>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-outline" />
              <span className="text-outline">{t('pages.tools.stats.readOnly', { count: readOnlyCount })}</span>
            </div>
            <span className="text-outline-variant">·</span>
            <div className="flex items-center gap-1.5 text-primary">
              <span className="material-symbols-outlined text-[14px]">shield_lock</span>
              <span>{t('pages.tools.stats.confirmation', { count: confirmCount })}</span>
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
            placeholder={t('pages.tools.search.placeholder')}
          />
          <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant">
            {t('pages.tools.search.badge')}
          </span>
        </div>
        <div className="md:col-span-4 bg-surface-container-low px-space-md py-2 rounded-xl flex items-center justify-between shadow-sm">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary text-[18px]">memory</span>
            <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant uppercase tracking-wider">
              {t('pages.tools.runtime.label')}
            </span>
          </div>
          <div className="flex items-center gap-1.5 font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-highest text-secondary">
            <span className="font-mono">{runtime.data?.provider ?? '--'}</span>
            <span className="text-outline">/</span>
            <span className={runtime.data?.available ? 'text-tertiary' : 'text-error'}>
              {runtime.data?.available ? t('pages.tools.runtime.available') : t('pages.tools.runtime.unavailable')}
            </span>
          </div>
        </div>
      </div>

      {/* Tool grid */}
      {tools.loading ? (
        <LoadingRow label={t('pages.tools.catalog.loading')} />
      ) : tools.error ? (
        <ErrorRow message={tools.error} onRetry={tools.reload} />
      ) : toolList.length === 0 ? (
        <EmptyRow message={t('pages.tools.catalog.empty')} />
      ) : visible.length === 0 ? (
        <EmptyRow message={t('pages.tools.catalog.emptyFiltered')} />
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
                      {t('pages.tools.tool.executionDeclaration')}
                    </span>
                    <div className="flex flex-wrap gap-1.5 font-label-mono-xs text-label-mono-xs">
                      {tool.read_only && (
                        <span className="px-2 py-0.5 rounded bg-tertiary-container/15 text-tertiary font-medium">
                          {t('pages.tools.tool.readOnly')}
                        </span>
                      )}
                      {tool.side_effect && (
                        <span className="px-2 py-0.5 rounded bg-secondary-container/20 text-secondary font-medium">
                          {t('pages.tools.tool.sideEffect')}
                        </span>
                      )}
                      {tool.requires_confirmation && (
                        <span className="px-2 py-0.5 rounded bg-primary/10 text-primary font-medium">
                          {t('pages.tools.tool.requiresConfirmation')}
                        </span>
                      )}
                      <span className={`px-2 py-0.5 rounded font-medium ${riskBadge(tool.risk_level)}`}>
                        {t('pages.tools.tool.risk', { risk: tool.risk_level })}
                      </span>
                    </div>
                  </div>

                  <div className="mt-space-md">
                    <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                      {t('pages.tools.tool.exposedParameters')}
                    </span>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {params.length === 0 ? (
                        <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container text-outline">
                          {t('pages.tools.tool.noParameters')}
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
                        {t('pages.tools.tool.noTelemetry')}
                      </span>
                    </div>
                    <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">
                      {t('common.notExposed')}
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
                    <span>{t('pages.tools.tool.viewSchema')}</span>
                  </button>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono truncate">
                    {tool.category ?? t('pages.tools.tool.noCategory')}
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
                  {t('pages.tools.health.title')}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-high text-secondary">
                  {overview?.model.provider ?? '--'}
                </span>
              </div>
              <span className="font-body-sm text-body-sm text-on-surface-variant">
                {t('pages.tools.health.description')}
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
            <span>{runtime.data?.available ? t('pages.tools.health.runtimeAvailable') : t('pages.tools.health.runtimeUnavailable')}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-gutter pt-space-sm">
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              {t('pages.tools.health.sandboxProvider')}
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {runtime.data?.provider ?? '--'}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant font-mono truncate">
              {runtime.data?.detail || t('pages.tools.health.noDetail')}
            </span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              {t('pages.tools.health.runtimeVersion')}
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {runtime.data?.version ?? '--'}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">{t('pages.tools.health.providerReported')}</span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              {t('pages.tools.health.toolsSkills')}
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {toolList.length} / {skillList.length}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">{t('pages.tools.health.backendCatalog')}</span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              {t('pages.tools.health.inferenceModel')}
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold truncate">
              {overview?.model.model ?? '--'}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              {overview?.model.configured ? t('pages.tools.health.configured') : t('pages.tools.health.notConfigured')}
            </span>
          </div>
          <div className="p-space-md rounded-lg bg-surface-container-lowest flex flex-col gap-1">
            <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
              {t('pages.tools.health.mcpServers')}
            </span>
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              {serverList.length}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              {t('pages.tools.health.registered')}
            </span>
          </div>
        </div>

        <p className="font-label-mono-xs text-label-mono-xs text-outline leading-5">
          {t('pages.tools.health.note')}
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
                    {selected.skill} · v{selected.version} · {selected.category ?? t('pages.tools.tool.noCategory')}
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
                  {t('pages.tools.tool.readOnly')}
                </span>
              )}
              {selected.side_effect && (
                <span className="px-2 py-0.5 rounded bg-secondary-container/20 text-secondary font-medium">
                  {t('pages.tools.tool.sideEffect')}
                </span>
              )}
              {selected.requires_confirmation && (
                <span className="px-2 py-0.5 rounded bg-primary/10 text-primary font-medium">
                  {t('pages.tools.tool.requiresConfirmation')}
                </span>
              )}
              <span className={`px-2 py-0.5 rounded font-medium ${riskBadge(selected.risk_level)}`}>
                {t('pages.tools.tool.risk', { risk: selected.risk_level })}
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

      {/* MCP server registration. Registering writes configuration; a remote
          server is tested immediately so the panel can show whether it is
          actually reachable and which tools it exposes. */}
      {showConnect && (
        <div
          className="fixed inset-0 z-50 bg-surface-container-lowest/80 backdrop-blur-md flex items-start md:items-center justify-center p-space-md overflow-y-auto"
          onClick={() => setShowConnect(false)}
        >
          <div
            className="relative w-full max-w-6xl max-h-[92vh] overflow-y-auto rounded-xl bg-surface-container-low shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            {/* Header */}
            <div className="flex flex-col gap-space-md p-space-lg border-b border-outline-variant/20">
              <div className="flex items-start justify-between gap-space-sm">
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex flex-wrap items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-secondary uppercase tracking-widest">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-secondary" />
                    <span>{t('pages.tools.header.breadcrumb')}</span>
                    <span className="text-outline-variant">/</span>
                    <span className="text-on-surface-variant">{t('pages.tools.connect.title')}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-space-sm mt-1">
                    <h2 className="font-headline-lg text-headline-lg font-semibold text-on-surface">
                      {t('pages.tools.connect.title')}
                    </h2>
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-container-high text-tertiary font-label-mono-xs text-label-mono-xs">
                      <span className="material-symbols-outlined text-[13px]">verified_user</span>
                      <span>{t('pages.tools.connect.registrationOnly')}</span>
                    </span>
                  </div>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">
                    {t('pages.tools.connect.subtitle')}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowConnect(false)}
                  aria-label={t('common.close')}
                  className="p-1 rounded text-outline hover:text-on-surface hover:bg-surface-container transition-colors"
                >
                  <span className="material-symbols-outlined text-[20px]">close</span>
                </button>
              </div>

              {/* Registration telemetry */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-space-sm">
                {[
                  {
                    label: t('pages.tools.connect.metrics.registered'),
                    value: serverList.length,
                    hint: t('pages.tools.connect.metrics.registeredHint'),
                    icon: 'dns',
                    tone: 'text-primary',
                  },
                  {
                    label: t('pages.tools.connect.metrics.enabled'),
                    value: enabledServers,
                    hint: t('pages.tools.connect.metrics.enabledHint'),
                    icon: 'toggle_on',
                    tone: 'text-tertiary',
                  },
                  {
                    label: t('pages.tools.connect.metrics.transports'),
                    value: transportOptions.length,
                    hint: t('pages.tools.connect.metrics.transportsHint'),
                    icon: 'swap_horiz',
                    tone: 'text-secondary',
                  },
                  {
                    label: t('pages.tools.connect.metrics.adapters'),
                    value: supportedServers,
                    hint: t('pages.tools.connect.metrics.adaptersHint', {
                      count: supportedServers,
                      total: serverList.length,
                    }),
                    icon: 'hub',
                    tone: 'text-on-surface-variant',
                  },
                ].map((metric) => (
                  <div
                    key={metric.label}
                    className="flex flex-col gap-0.5 p-space-sm rounded bg-surface-container-lowest border border-outline-variant/20"
                  >
                    <div className="flex items-center justify-between gap-space-xs">
                      <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider truncate">
                        {metric.label}
                      </span>
                      <span className={`material-symbols-outlined text-[16px] ${metric.tone}`}>
                        {metric.icon}
                      </span>
                    </div>
                    <span className="font-headline-sm text-headline-sm font-semibold text-on-surface">
                      {metric.value}
                    </span>
                    <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                      {metric.hint}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md p-space-lg items-start">
              {formError && (
                <div
                  className="lg:col-span-12 p-space-sm rounded bg-error-container/30 border border-error/40 text-error font-body-sm text-body-sm flex items-center gap-1.5"
                  role="alert"
                >
                  <span className="material-symbols-outlined text-[16px]">error</span>
                  {formError}
                </div>
              )}
              {formNotice && (
                <div className="lg:col-span-12 p-space-sm rounded bg-tertiary-container/20 border border-tertiary/40 text-tertiary font-body-sm text-body-sm flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[16px]">check_circle</span>
                  {formNotice}
                </div>
              )}
              {/* Form */}
              <div className="lg:col-span-7 flex flex-col gap-space-md">
                <div className="p-space-md rounded bg-surface-container-lowest border border-outline-variant/20 flex flex-col gap-space-md">
                  <div className="flex items-start justify-between gap-space-sm">
                    <div className="flex flex-col min-w-0">
                      <span className="font-body-md text-body-md font-semibold text-on-surface">
                        {t('pages.tools.connect.formTitle')}
                      </span>
                      <span className="font-label-mono-xs text-label-mono-xs text-outline">
                        {t('pages.tools.connect.formHint')}
                      </span>
                    </div>
                    <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container text-secondary whitespace-nowrap">
                      {TRANSPORT_LABELS[form.transport]}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-space-sm">
                    <label className="flex flex-col gap-1">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                        {t('common.name')}
                      </span>
                      <input
                        value={form.name}
                        onChange={(event) => setForm({ ...form, name: event.target.value })}
                        placeholder="filesystem"
                        className="bg-surface-container-low rounded px-space-sm py-2 font-body-sm text-body-sm text-on-surface placeholder:text-outline outline-none border border-outline-variant/30 focus:border-primary/60 transition-colors"
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                        {t('common.description')}
                      </span>
                      <input
                        value={form.description}
                        onChange={(event) => setForm({ ...form, description: event.target.value })}
                        placeholder={t('pages.tools.connect.descriptionPlaceholder')}
                        className="bg-surface-container-low rounded px-space-sm py-2 font-body-sm text-body-sm text-on-surface placeholder:text-outline outline-none border border-outline-variant/30 focus:border-primary/60 transition-colors"
                      />
                    </label>
                  </div>

                  <div className="flex flex-col gap-1">
                    <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                      {t('pages.tools.connect.transport')}
                    </span>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
                      {transportOptions.map((transport) => (
                        <button
                          key={transport}
                          type="button"
                          onClick={() => setForm({ ...form, transport })}
                          className={`flex items-center justify-center gap-1.5 px-3 py-1.5 rounded font-label-mono-xs text-label-mono-xs transition-colors border ${
                            form.transport === transport
                              ? 'bg-primary text-on-primary border-primary font-semibold'
                              : 'bg-surface-container text-on-surface-variant border-outline-variant/20 hover:bg-surface-container-high hover:text-on-surface'
                          }`}
                        >
                          <span className="material-symbols-outlined text-[14px]">
                            {TRANSPORT_ICONS[transport] ?? 'cable'}
                          </span>
                          <span>{TRANSPORT_LABELS[transport]}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <label className="flex flex-col gap-1">
                    <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                      {form.transport === 'stdio'
                        ? t('pages.tools.connect.commandLabel')
                        : t('pages.tools.connect.endpointLabel')}
                    </span>
                    <input
                      value={form.command}
                      onChange={(event) => setForm({ ...form, command: event.target.value })}
                      placeholder={
                        form.transport === 'stdio'
                          ? 'npx -y @modelcontextprotocol/server-filesystem /tmp'
                          : 'https://api.githubcopilot.com/mcp/'
                      }
                      className="bg-surface-container-low rounded px-space-sm py-2 font-code-base text-code-base text-on-surface placeholder:text-outline outline-none border border-outline-variant/30 focus:border-secondary/60 transition-colors"
                    />
                  </label>

                  {form.transport === 'stdio' ? (
                    <label className="flex flex-col gap-1">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                        {t('pages.tools.connect.envLabel')}
                      </span>
                      <textarea
                        value={form.envText}
                        onChange={(event) => setForm({ ...form, envText: event.target.value })}
                        rows={3}
                        className="bg-surface-container-low rounded px-space-sm py-2 font-code-base text-code-base text-on-surface placeholder:text-outline outline-none border border-outline-variant/30 focus:border-secondary/60 transition-colors resize-y"
                      />
                      <span className="font-label-mono-xs text-label-mono-xs text-outline leading-4">
                        {t('pages.tools.connect.stdioHint')}
                      </span>
                    </label>
                  ) : (
                    <label className="flex flex-col gap-1">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                        {t('pages.tools.connect.headersLabel')}
                      </span>
                      <textarea
                        value={form.headersText}
                        onChange={(event) => setForm({ ...form, headersText: event.target.value })}
                        rows={3}
                        placeholder={t('pages.tools.connect.headersPlaceholder')}
                        className="bg-surface-container-low rounded px-space-sm py-2 font-code-base text-code-base text-on-surface placeholder:text-outline outline-none border border-outline-variant/30 focus:border-secondary/60 transition-colors resize-y"
                      />
                      <span className="font-label-mono-xs text-label-mono-xs text-outline leading-4">
                        {t('pages.tools.connect.secretHint')}
                      </span>
                    </label>
                  )}
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm p-space-sm rounded bg-surface-container-lowest border border-outline-variant/20">
                  <p className="font-label-mono-xs text-label-mono-xs text-outline leading-4 max-w-md">
                    {t('pages.tools.connect.noteGeneric')}
                  </p>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => setShowConnect(false)}
                      className="px-space-md py-1.5 rounded bg-surface-container text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors font-body-sm text-body-sm"
                    >
                      {t('common.cancel')}
                    </button>
                    <button
                      type="button"
                      onClick={submitServer}
                      disabled={submitting}
                      className="flex items-center gap-1.5 px-space-md py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-fixed-dim transition-all active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      <span className="material-symbols-outlined text-[16px]">
                        {submitting ? 'progress_activity' : 'add_link'}
                      </span>
                      {submitting
                        ? t('pages.tools.connect.submitting')
                        : t('pages.tools.connect.submit')}
                    </button>
                  </div>
                </div>
              </div>

              {/* Registry */}
              <div className="lg:col-span-5 flex flex-col gap-space-md">
                <div className="p-space-sm rounded bg-secondary/5 border border-secondary/20 flex flex-col gap-1">
                  <div className="flex items-center gap-1.5 text-secondary">
                    <span className="material-symbols-outlined text-[16px]">info</span>
                    <span className="font-label-mono-xs text-label-mono-xs uppercase tracking-wider font-semibold">
                      {t('pages.tools.connect.registrationOnly')}
                    </span>
                  </div>
                  <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                    {t('pages.tools.connect.registrationNote')}
                  </p>
                </div>

                <div className="p-space-md rounded bg-surface-container-lowest border border-outline-variant/20 flex flex-col gap-space-sm">
                  <div className="flex items-center justify-between gap-space-sm">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="material-symbols-outlined text-[16px] text-secondary">lan</span>
                      <span className="font-body-md text-body-md font-semibold text-on-surface truncate">
                        {t('pages.tools.connect.registeredServers')}
                      </span>
                    </div>
                    <span className="font-label-mono-xs text-label-mono-xs bg-surface-container-high text-secondary px-1.5 py-0.5 rounded font-mono">
                      {servers.data?.registered ?? serverList.length}
                    </span>
                  </div>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    {t('pages.tools.connect.registeredHint')}
                  </span>

                  {servers.loading ? (
                    <p className="font-body-sm text-body-sm text-on-surface-variant">
                      {t('pages.tools.connect.loading')}
                    </p>
                  ) : servers.error ? (
                    <p className="font-body-sm text-body-sm text-error">{servers.error}</p>
                  ) : serverList.length === 0 ? (
                    <div className="p-space-md rounded bg-surface-container border border-dashed border-outline-variant/30 flex flex-col items-center text-center gap-1">
                      <span className="material-symbols-outlined text-[24px] text-outline">dns</span>
                      <span className="font-body-sm text-body-sm font-medium text-on-surface">
                        {t('pages.tools.connect.noServers')}
                      </span>
                      <span className="font-label-mono-xs text-label-mono-xs text-outline">
                        {t('pages.tools.connect.emptyHint')}
                      </span>
                    </div>
                  ) : (
                    <ul className="flex flex-col gap-1.5">
                      {serverList.map((server) => {
                        const result = testResults[server.id];
                        return (
                        <li
                          key={server.id}
                          className="p-space-sm rounded bg-surface-container border border-outline-variant/20 flex flex-col gap-1.5"
                        >
                          <div className="flex items-start justify-between gap-space-sm">
                            <div className="flex items-start gap-2 min-w-0">
                              <div className="w-7 h-7 rounded bg-surface-container-high flex items-center justify-center text-secondary shrink-0">
                                <span className="material-symbols-outlined text-[16px]">
                                  {TRANSPORT_ICONS[server.transport_type] ?? 'cable'}
                                </span>
                              </div>
                              <div className="flex flex-col min-w-0">
                                <div className="flex flex-wrap items-center gap-1">
                                  <span className="font-body-sm text-body-sm font-semibold text-on-surface truncate">
                                    {server.name}
                                  </span>
                                  <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-high text-secondary">
                                    {TRANSPORT_LABELS[server.transport_type] ?? server.transport_type}
                                  </span>
                                  {!server.transport_supported && (
                                    <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-error-container/30 text-error">
                                      {t('pages.tools.connect.noAdapter')}
                                    </span>
                                  )}
                                  {!server.enabled && (
                                    <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-high text-outline">
                                      {t('pages.tools.connect.disabled')}
                                    </span>
                                  )}
                                </div>
                                <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono truncate">
                                  {server.endpoint}
                                </span>
                                {server.description && (
                                  <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant truncate">
                                    {server.description}
                                  </span>
                                )}
                              </div>
                            </div>
                            <span className={`w-2 h-2 rounded-full mt-1 shrink-0 ${statusDot(server)}`} />
                          </div>

                          <div className="flex flex-wrap items-center gap-2 font-label-mono-xs text-label-mono-xs">
                            <span
                              className={
                                server.status === 'READY'
                                  ? 'text-tertiary'
                                  : server.status === 'ERROR'
                                    ? 'text-error'
                                    : 'text-outline'
                              }
                            >
                              {serverStatusLabel(server.status)}
                            </span>
                            {result && (
                              <span className={result.ok ? 'text-secondary' : 'text-error'}>
                                {result.ok
                                  ? t('pages.tools.connect.toolsDiscovered', { count: result.tool_count })
                                  : t('pages.tools.connect.connectionFailedShort')}
                              </span>
                            )}
                            {server.last_connected_at && (
                              <span className="text-outline">
                                {t('pages.tools.connect.lastConnected')}
                              </span>
                            )}
                          </div>

                          {result && !result.ok && result.error && (
                            <p className="font-label-mono-xs text-label-mono-xs text-error leading-4 break-words">
                              {result.error}
                            </p>
                          )}

                          {result?.ok && result.tools.length > 0 && (
                            <details className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                              <summary className="cursor-pointer text-secondary hover:text-on-surface">
                                {t('pages.tools.connect.toolsDiscovered', { count: result.tool_count })}
                              </summary>
                              <ul className="mt-1 flex flex-col gap-0.5 pl-2">
                                {result.tools.slice(0, 8).map((tool) => (
                                  <li key={tool.name} className="font-mono truncate">
                                    {tool.name}
                                  </li>
                                ))}
                                {result.tool_count > 8 && (
                                  <li className="text-outline">+{result.tool_count - 8}</li>
                                )}
                              </ul>
                            </details>
                          )}

                          <div className="flex flex-wrap items-center justify-between gap-space-sm pt-1 border-t border-outline-variant/10">
                            <span
                              className={`font-label-mono-xs text-label-mono-xs uppercase tracking-wider ${
                                server.enabled ? 'text-tertiary' : 'text-outline'
                              }`}
                            >
                              {server.enabled
                                ? t('pages.tools.connect.enabled')
                                : t('pages.tools.connect.disabled')}
                            </span>
                            <div className="flex items-center gap-1 shrink-0">
                              <button
                                type="button"
                                onClick={() => testServer(server)}
                                disabled={testingServer === server.id || busyServer === server.id}
                                className="px-2.5 py-1 rounded bg-secondary-container/20 hover:bg-secondary-container/40 text-secondary font-label-mono-xs text-label-mono-xs transition-colors disabled:opacity-60 flex items-center gap-1"
                              >
                                <span className="material-symbols-outlined text-[13px]">
                                  {testingServer === server.id ? 'progress_activity' : 'cable'}
                                </span>
                                {testingServer === server.id
                                  ? t('pages.tools.connect.testing')
                                  : t('pages.tools.connect.test')}
                              </button>
                              <button
                                type="button"
                                onClick={() => toggleServer(server)}
                                disabled={busyServer === server.id || testingServer === server.id}
                                className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-mono-xs text-label-mono-xs transition-colors disabled:opacity-60"
                              >
                                {server.enabled
                                  ? t('pages.tools.connect.disable')
                                  : t('pages.tools.connect.enable')}
                              </button>
                              <button
                                type="button"
                                onClick={() => removeServer(server)}
                                disabled={busyServer === server.id || testingServer === server.id}
                                className="px-2.5 py-1 rounded bg-error-container/30 hover:bg-error-container/50 text-error font-label-mono-xs text-label-mono-xs transition-colors disabled:opacity-60"
                              >
                                {t('common.delete')}
                              </button>
                            </div>
                          </div>
                        </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
