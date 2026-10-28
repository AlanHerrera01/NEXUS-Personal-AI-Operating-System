import { useState, type FormEvent } from 'react';
import { useAsyncData } from '../hooks/useAsyncData';
import { useI18n } from '../hooks/useI18n';
import { useOverview } from '../hooks/useOverview';
import type { MessageKey } from '../i18n/types';
import { memoryApi } from '../services/api/memoryApi';
import { ApiError } from '../services/api/apiClient';
import { EmptyRow, ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { MemoryDetail, MemoryImportance, MemoryType } from '../types';

type TypeFilter = 'ALL' | MemoryType;

interface TypeMeta {
  labelKey: MessageKey;
  badge: string;
  bar: string;
  count: string;
}

/* The API code stays the map key; only the label is copy, so it is stored as a
   key and resolved at render. */
const TYPE_META: Record<MemoryType, TypeMeta> = {
  PREFERENCE: { labelKey: 'pages.memory.types.preference', badge: 'bg-primary/10 text-primary', bar: 'bg-primary', count: 'text-primary' },
  SEMANTIC: { labelKey: 'pages.memory.types.semantic', badge: 'bg-secondary/10 text-secondary', bar: 'bg-secondary', count: 'text-secondary' },
  EPISODIC: { labelKey: 'pages.memory.types.episodic', badge: 'bg-tertiary/10 text-tertiary', bar: 'bg-tertiary', count: 'text-tertiary' },
};

/** Persist the currently loaded memories as newline-delimited JSON. */
function downloadJsonl(items: MemoryDetail[], agentId: string | null) {
  if (items.length === 0) return;
  const blob = new Blob([items.map((item) => JSON.stringify(item)).join('\n')], {
    type: 'application/x-ndjson',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `nexus-memories-${agentId?.slice(0, 8) ?? 'agent'}.jsonl`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function Memory() {
  const { t, formatNumber } = useI18n();
  const { data: overview, connected } = useOverview();
  const agentId = overview?.agent?.id ?? null;

  const [refreshKey, setRefreshKey] = useState(0);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('ALL');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<MemoryDetail[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  const [draft, setDraft] = useState<{
    content: string;
    type: MemoryType;
    importance: MemoryImportance;
  }>({ content: '', type: 'SEMANTIC', importance: 'MEDIUM' });
  const [saving, setSaving] = useState(false);

  const reload = () => setRefreshKey((key) => key + 1);

  const memories = useAsyncData(
    () => (agentId ? memoryApi.listMemories(agentId) : Promise.resolve<MemoryDetail[]>([])),
    [agentId, refreshKey],
  );

  const items = memories.data ?? [];
  const base = results ?? items;
  const visible = typeFilter === 'ALL' ? base : base.filter((item) => item.memory_type === typeFilter);

  const counts = {
    EPISODIC: items.filter((item) => item.memory_type === 'EPISODIC').length,
    SEMANTIC: items.filter((item) => item.memory_type === 'SEMANTIC').length,
    PREFERENCE: items.filter((item) => item.memory_type === 'PREFERENCE').length,
  };

  const runSearch = async () => {
    if (!agentId || query.trim() === '') {
      setResults(null);
      return;
    }
    setSearching(true);
    setActionError(null);
    try {
      setResults(await memoryApi.searchMemories(agentId, query.trim()));
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : t('pages.memory.errors.search'));
    } finally {
      setSearching(false);
    }
  };

  const clearSearch = () => {
    setResults(null);
    setQuery('');
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!agentId || draft.content.trim() === '') return;
    setSaving(true);
    setActionError(null);
    try {
      await memoryApi.saveMemory({
        agent_id: agentId,
        content: draft.content.trim(),
        memory_type: draft.type,
        source: 'USER_EXPLICIT',
        importance: draft.importance,
      });
      setDraft({ content: '', type: 'SEMANTIC', importance: 'MEDIUM' });
      setShowNew(false);
      setResults(null);
      reload();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : t('pages.memory.errors.save'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (memoryId: string) => {
    if (!agentId) return;
    setBusy(memoryId);
    setActionError(null);
    try {
      await memoryApi.deleteMemory(memoryId, agentId);
      setResults((prev) => prev?.filter((item) => item.id !== memoryId) ?? null);
      reload();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : t('pages.memory.errors.remove'));
    } finally {
      setBusy(null);
    }
  };

  const clearAll = async () => {
    if (!agentId) return;
    if (!window.confirm(t('pages.memory.confirm.clearAll'))) return;
    setActionError(null);
    try {
      await memoryApi.clearMemories(agentId);
      setResults(null);
      reload();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : t('pages.memory.errors.clear'));
    }
  };

  const tabs: { key: TypeFilter; label: string; count: number; tone: string }[] = [
    { key: 'ALL', label: t('common.all'), count: items.length, tone: 'text-on-surface-variant' },
    { key: 'EPISODIC', label: t('pages.memory.tabs.episodic'), count: counts.EPISODIC, tone: TYPE_META.EPISODIC.count },
    { key: 'SEMANTIC', label: t('pages.memory.tabs.semantic'), count: counts.SEMANTIC, tone: TYPE_META.SEMANTIC.count },
    { key: 'PREFERENCE', label: t('pages.memory.tabs.preference'), count: counts.PREFERENCE, tone: TYPE_META.PREFERENCE.count },
  ];

  return (
    <div className="flex flex-col w-full">
      {/* Header + metric ribbon with ambient glow */}
      <div className="relative w-full overflow-hidden">
        <div className="absolute -top-32 left-1/4 w-[500px] h-[250px] bg-primary/5 blur-[120px] pointer-events-none rounded-full" />
        <div className="absolute top-20 right-10 w-[380px] h-[180px] bg-secondary/5 blur-[100px] pointer-events-none rounded-full" />

        <div className="relative px-margin pt-space-lg pb-space-md flex flex-col gap-space-md max-w-[1720px] mx-auto w-full">
          <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-space-md">
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-outline flex-wrap">
                <span className="text-tertiary font-semibold tracking-wider uppercase">
                  {t('pages.memory.header.brand')}
                </span>
                <span>/</span>
                <span className="text-on-surface-variant uppercase">
                  {t('pages.memory.header.subsystem')}
                </span>
                <span>/</span>
                <span className="text-secondary font-mono">{t('pages.memory.header.engine')}</span>
              </div>
              <div className="flex items-baseline gap-space-md flex-wrap mt-0.5">
                <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight font-semibold">
                  {t('pages.memory.header.title')}
                </h1>
                <span className="font-body-md text-body-md text-on-surface-variant">
                  {t('pages.memory.header.description')}
                </span>
              </div>
            </div>

            {/* Firewall banner */}
            <div className="bg-surface-container-low px-space-md py-space-sm rounded-lg flex items-center justify-between gap-space-lg shadow-sm">
              <div className="flex items-center gap-space-sm">
                <div className="relative flex items-center justify-center w-7 h-7 rounded bg-tertiary-container/20 text-tertiary flex-shrink-0">
                  <span className="material-symbols-outlined text-[18px]">verified_user</span>
                  {connected && (
                    <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-tertiary animate-ping" />
                  )}
                </div>
                <div className="flex flex-col">
                  <div className="flex items-center gap-space-xs">
                    <span className="font-label-mono-xs text-label-mono-xs text-tertiary font-semibold tracking-wider">
                      {connected
                        ? t('pages.memory.firewall.active')
                        : t('pages.memory.firewall.offline')}
                    </span>
                    <span className="font-label-mono-xs text-label-mono-xs bg-surface-container-high px-1.5 rounded text-outline font-mono">
                      {t('pages.memory.firewall.trust', {
                        decision: overview?.trust.default_decision ?? '--',
                      })}
                    </span>
                  </div>
                  <span className="font-body-sm text-body-sm text-outline">
                    {t('pages.memory.firewall.description')}
                  </span>
                </div>
              </div>
              <span className="hidden sm:flex font-label-mono-xs text-label-mono-xs px-space-xs py-1 bg-surface-container rounded text-tertiary font-mono whitespace-nowrap">
                {agentId
                  ? t('pages.memory.agent.label', { id: agentId.slice(0, 8) })
                  : t('pages.memory.agent.none')}
              </span>
            </div>
          </div>

          {/* Metric ribbon — every node is a real value */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-space-sm mt-space-xs">
            <MetricNode
              label={t('pages.memory.metrics.memories')}
              icon="scatter_plot"
              tone="text-primary"
              value={formatNumber(items.length)}
              caption={t('pages.memory.metrics.loadedMax')}
            />
            <MetricNode
              label={t('pages.memory.metrics.episodic')}
              icon="history"
              tone="text-tertiary"
              value={formatNumber(counts.EPISODIC)}
              caption="EPISODIC"
            />
            <MetricNode
              label={t('pages.memory.metrics.semantic')}
              icon="hub"
              tone="text-secondary"
              value={formatNumber(counts.SEMANTIC)}
              caption="SEMANTIC"
            />
            <MetricNode
              label={t('pages.memory.metrics.preference')}
              icon="tune"
              tone="text-primary-container"
              value={formatNumber(counts.PREFERENCE)}
              caption="PREFERENCE"
            />
            <MetricNode
              label={t('pages.memory.metrics.vectorEngine')}
              icon="database"
              tone={connected ? 'text-tertiary' : 'text-error'}
              value={
                connected ? t('pages.memory.metrics.connected') : t('pages.memory.metrics.offline')
              }
              caption={
                overview?.system.database
                  ? t('pages.memory.metrics.db', { value: overview.system.database })
                  : '--'
              }
            />
          </div>
        </div>
      </div>

      {/* Search, filters and actions */}
      <div className="px-margin py-space-sm max-w-[1720px] mx-auto w-full">
        <div className="bg-surface-container-low p-space-sm rounded-lg flex flex-col lg:flex-row lg:items-center justify-between gap-space-sm shadow-sm">
          <div className="relative flex-1 min-w-[280px]">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-[18px]">
              search
            </span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void runSearch();
              }}
              placeholder={t('pages.memory.search.placeholder')}
              className="w-full bg-surface-container-lowest text-on-surface font-body-sm text-body-sm pl-9 pr-14 py-2 rounded focus:outline-none focus:bg-surface-container transition-colors placeholder:text-outline"
            />
            <kbd className="absolute right-2.5 top-1/2 -translate-y-1/2 font-label-mono-xs text-label-mono-xs bg-surface-container-high px-1.5 py-0.5 rounded text-outline font-mono">
              ⏎
            </kbd>
          </div>

          <div className="flex items-center justify-between lg:justify-end gap-space-sm flex-wrap">
            <div className="flex items-center gap-1 bg-surface-container-lowest p-1 rounded">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setTypeFilter(tab.key)}
                  className={`px-space-sm py-1 rounded font-label-mono-sm text-label-mono-sm flex items-center gap-1.5 transition-all ${
                    typeFilter === tab.key
                      ? 'bg-surface-container text-on-surface font-medium'
                      : 'hover:bg-surface-container/60 text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span className={`bg-surface-container-high px-1.5 rounded font-mono text-[10px] ${tab.tone}`}>
                    {formatNumber(tab.count)}
                  </span>
                </button>
              ))}
            </div>
            <div className="flex items-center gap-space-xs">
              <button
                type="button"
                disabled={searching}
                onClick={() => void runSearch()}
                className="bg-primary text-on-primary hover:bg-primary-container disabled:opacity-50 px-space-sm py-1.5 rounded font-body-sm text-body-sm font-medium transition-colors"
              >
                {searching ? t('pages.memory.search.searching') : t('common.search')}
              </button>
              {results && (
                <button
                  type="button"
                  onClick={clearSearch}
                  className="bg-surface-container-lowest hover:bg-surface-container px-space-sm py-1.5 rounded text-on-surface-variant hover:text-on-surface font-body-sm text-body-sm transition-colors"
                >
                  {t('pages.memory.search.clear')}
                </button>
              )}
              <button
                type="button"
                onClick={reload}
                className="bg-surface-container-lowest hover:bg-surface-container px-space-sm py-1.5 rounded text-on-surface-variant hover:text-on-surface font-body-sm text-body-sm flex items-center gap-1 transition-colors"
              >
                <span className="material-symbols-outlined text-[16px]">refresh</span>
                {t('common.reload')}
              </button>
              <button
                type="button"
                onClick={() => downloadJsonl(items, agentId)}
                disabled={items.length === 0}
                className="bg-surface-container-lowest hover:bg-surface-container disabled:opacity-50 px-space-sm py-1.5 rounded text-secondary flex items-center gap-1 font-body-sm text-body-sm transition-colors"
              >
                <span className="material-symbols-outlined text-[16px]">download</span>
                {t('pages.memory.actions.export')}
              </button>
              <button
                type="button"
                onClick={() => setShowNew((value) => !value)}
                disabled={!agentId}
                className="bg-surface-container-lowest hover:bg-surface-container disabled:opacity-50 px-space-sm py-1.5 rounded text-primary flex items-center gap-1 font-body-sm text-body-sm transition-colors"
              >
                <span className="material-symbols-outlined text-[16px]">add</span>
                {t('pages.memory.actions.new')}
              </button>
            </div>
          </div>
        </div>

        {actionError && (
          <div className="mt-space-sm">
            <ErrorRow message={actionError} />
          </div>
        )}
      </div>

      {/* Work area */}
      <div className="px-margin py-space-sm pb-space-xl max-w-[1720px] mx-auto w-full grid grid-cols-1 lg:grid-cols-12 gap-space-md">
        {/* Records stream */}
        <div className="lg:col-span-8 flex flex-col gap-space-sm min-w-0">
          {showNew && (
            <form
              onSubmit={save}
              className="bg-surface-container-low rounded-lg p-space-md flex flex-col gap-space-sm shadow-sm"
            >
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                {t('pages.memory.form.title')}
              </span>
              <textarea
                value={draft.content}
                onChange={(event) => setDraft({ ...draft, content: event.target.value })}
                rows={2}
                placeholder={t('pages.memory.form.placeholder')}
                className="bg-surface-container-lowest rounded px-space-sm py-2 font-body-sm text-body-sm text-on-surface outline-none focus:ring-1 focus:ring-primary resize-none"
              />
              <div className="flex flex-wrap items-center gap-space-sm">
                <select
                  value={draft.type}
                  onChange={(event) => setDraft({ ...draft, type: event.target.value as MemoryType })}
                  className="bg-surface-container-lowest rounded px-space-sm py-1 font-code-base text-code-base text-on-surface outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="EPISODIC">EPISODIC</option>
                  <option value="SEMANTIC">SEMANTIC</option>
                  <option value="PREFERENCE">PREFERENCE</option>
                </select>
                <select
                  value={draft.importance}
                  onChange={(event) =>
                    setDraft({ ...draft, importance: event.target.value as MemoryImportance })
                  }
                  className="bg-surface-container-lowest rounded px-space-sm py-1 font-code-base text-code-base text-on-surface outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="LOW">LOW</option>
                  <option value="MEDIUM">MEDIUM</option>
                  <option value="HIGH">HIGH</option>
                </select>
                <button
                  type="submit"
                  disabled={saving || draft.content.trim() === ''}
                  className="bg-primary text-on-primary hover:bg-primary-container disabled:opacity-50 rounded px-space-md py-1.5 font-body-sm text-body-sm font-medium transition-colors"
                >
                  {saving ? t('common.saving') : t('common.save')}
                </button>
              </div>
            </form>
          )}

          <div className="flex items-center justify-between px-space-xs">
            <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
              <span className="material-symbols-outlined text-[15px] text-secondary">memory</span>
              <span>
                {results ? t('pages.memory.stream.results') : t('pages.memory.stream.synced')}{' '}
                {t('pages.memory.stream.showing', {
                  shown: formatNumber(visible.length),
                  total: formatNumber(items.length),
                })}
              </span>
            </div>
            <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-tertiary">
              <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-tertiary' : 'bg-error'}`} />
              <span>
                {connected ? t('pages.memory.stream.online') : t('pages.memory.stream.offline')}
              </span>
            </div>
          </div>

          {!agentId ? (
            <EmptyRow message={t('pages.memory.empty.noAgent')} />
          ) : memories.loading && !results ? (
            <LoadingRow label={t('pages.memory.empty.loading')} />
          ) : memories.error && !results ? (
            <ErrorRow message={memories.error} onRetry={reload} />
          ) : visible.length === 0 ? (
            <EmptyRow
              message={
                results
                  ? t('pages.memory.empty.noResults')
                  : typeFilter === 'ALL'
                    ? t('pages.memory.empty.noMemories')
                    : t('pages.memory.empty.noType')
              }
            />
          ) : (
            visible.map((memory) => {
              const meta = TYPE_META[memory.memory_type as MemoryType] ?? TYPE_META.SEMANTIC;
              return (
                <div
                  key={memory.id}
                  className="bg-surface-container-low rounded-lg p-space-md flex flex-col justify-between hover:bg-surface-container/70 transition-all shadow-sm"
                >
                  <div className="flex flex-col gap-space-sm">
                    <div className="flex items-center justify-between flex-wrap gap-space-xs">
                      <div className="flex items-center gap-space-xs">
                        <span
                          className={`px-2 py-0.5 rounded font-label-mono-xs text-label-mono-xs font-medium uppercase ${meta.badge}`}
                        >
                          {t(meta.labelKey)}
                        </span>
                        <span className="font-code-base text-code-base text-on-surface font-medium">
                          {memory.id.slice(0, 8)}
                        </span>
                      </div>
                      <div className="flex items-center gap-space-xs">
                        <span className="px-1.5 py-0.5 rounded bg-surface-container-lowest font-label-mono-xs text-label-mono-xs text-on-surface-variant font-mono">
                          {t('pages.memory.card.importance', { value: memory.importance })}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-surface-container-lowest font-label-mono-xs text-label-mono-xs text-on-surface-variant font-mono">
                          {memory.persistence_decision}
                        </span>
                      </div>
                    </div>

                    <p className="font-body-md text-body-md text-on-surface leading-relaxed pl-1 whitespace-pre-wrap">
                      {memory.content}
                    </p>

                    <div className="bg-surface-container-lowest/80 rounded p-space-xs px-space-sm flex items-center justify-between text-on-surface-variant font-label-mono-xs text-label-mono-xs flex-wrap gap-space-xs">
                      <div className="flex items-center gap-2">
                        <span className="text-outline">{t('pages.memory.card.source')}</span>
                        <span className="text-on-surface">{memory.source}</span>
                      </div>
                      <div className="flex items-center gap-1 text-tertiary">
                        <span className="material-symbols-outlined text-[14px]">lock_reset</span>
                        <span>
                          {memory.persistence_decision === 'SAVE'
                            ? t('pages.memory.card.persisted')
                            : t('pages.memory.card.notPersisted')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="mt-space-md pt-space-xs flex items-center justify-between">
                    <span className="font-label-mono-xs text-label-mono-xs text-outline">
                      {t('pages.memory.agent.label', { id: memory.agent_id.slice(0, 8) })}
                    </span>
                    <button
                      type="button"
                      disabled={busy === memory.id}
                      onClick={() => void remove(memory.id)}
                      className="bg-surface-container hover:bg-error-container text-on-surface-variant hover:text-error disabled:opacity-50 px-space-sm py-1 rounded font-body-sm text-body-sm flex items-center gap-1 transition-colors"
                    >
                      <span className="material-symbols-outlined text-[15px]">delete</span>
                      <span>{t('common.delete')}</span>
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Security, telemetry & auditing */}
        <div className="lg:col-span-4 flex flex-col gap-space-md">
          {/* Firewall policy */}
          <div className="bg-surface-container-low rounded-lg p-space-md flex flex-col gap-space-md shadow-sm">
            <div className="flex items-center gap-space-xs text-secondary font-label-mono-xs text-label-mono-xs font-semibold tracking-wider uppercase">
              <span className="material-symbols-outlined text-[16px]">shield_with_heart</span>
              <span>{t('pages.memory.policy.heading')}</span>
            </div>
            <div className="flex flex-col gap-space-xs">
              <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold tracking-tight leading-snug">
                {t('pages.memory.policy.title')}
              </h3>
              <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                {t('pages.memory.policy.bodyBefore')}
                <span className="font-code-base text-code-base text-secondary">
                  {t('pages.memory.policy.heuristic')}
                </span>
                {t('pages.memory.policy.bodyAfter')}
              </p>
            </div>
            <div className="bg-surface-container-lowest p-space-sm rounded flex flex-col gap-space-xs">
              <div className="flex items-center justify-between text-on-surface">
                <span className="font-label-mono-xs text-label-mono-xs font-medium">
                  {t('pages.memory.policy.decision')}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-tertiary font-mono">
                  {overview?.trust.default_decision ?? '--'}
                </span>
              </div>
              <div className="flex items-center justify-between text-on-surface-variant">
                <span className="font-label-mono-xs text-label-mono-xs">
                  {t('pages.memory.policy.persistence')}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs font-mono">
                  SAVE / DO_NOT_SAVE
                </span>
              </div>
            </div>
          </div>

          {/* Storage layer */}
          <div className="relative rounded-lg overflow-hidden h-36 bg-surface-container-lowest flex items-end">
            <div className="absolute inset-0 bg-gradient-to-br from-primary/20 via-surface-container to-secondary/10" />
            <span className="material-symbols-outlined absolute right-4 top-4 text-[64px] text-primary/20">
              database
            </span>
            <div className="relative p-space-sm flex flex-col">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase font-mono">
                {t('pages.memory.storage.label')}
              </span>
              <span className="font-body-sm text-body-sm text-on-surface font-semibold">
                {t('pages.memory.storage.engine')}
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                {overview?.system.database === 'up'
                  ? t('pages.memory.storage.connected')
                  : t('pages.memory.storage.unavailable')}
              </span>
            </div>
          </div>

          {/* Operations */}
          <div className="flex flex-col gap-1 pt-space-xs">
            <button
              type="button"
              onClick={() => downloadJsonl(items, agentId)}
              disabled={items.length === 0}
              className="flex items-center justify-between p-space-xs rounded hover:bg-surface-container text-on-surface hover:text-secondary disabled:opacity-50 transition-colors group"
            >
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-[16px] text-outline group-hover:text-secondary transition-colors">
                  file_download
                </span>
                <span className="font-body-sm text-body-sm">
                  {t('pages.memory.operations.download')}
                </span>
              </div>
              <span className="material-symbols-outlined text-[16px] text-outline">chevron_right</span>
            </button>
            <button
              type="button"
              onClick={() => void clearAll()}
              disabled={!agentId || items.length === 0}
              className="flex items-center justify-between p-space-xs rounded hover:bg-surface-container text-on-surface hover:text-error disabled:opacity-50 transition-colors group"
            >
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-[16px] text-outline group-hover:text-error transition-colors">
                  delete_sweep
                </span>
                <span className="font-body-sm text-body-sm">
                  {t('pages.memory.operations.clear')}
                </span>
              </div>
              <span className="font-label-mono-xs text-label-mono-xs bg-surface-container px-1 rounded text-outline font-mono">
                {formatNumber(items.length)}
              </span>
            </button>
          </div>

          {/* Firewall live log (not exposed by the backend) */}
          <div className="bg-surface-container-low rounded-lg p-space-md flex flex-col gap-space-sm shadow-sm">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider font-semibold">
                {t('pages.memory.log.title')}
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">
                {t('common.notExposed')}
              </span>
            </div>
            <div className="bg-surface-container-lowest p-space-sm rounded">
              <span className="font-label-mono-xs text-label-mono-xs text-outline leading-5 block">
                {t('pages.memory.log.body')}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface MetricNodeProps {
  label: string;
  icon: string;
  tone: string;
  value: string | number;
  caption: string;
}

function MetricNode({ label, icon, tone, value, caption }: MetricNodeProps) {
  return (
    <div className="bg-surface-container-low p-space-sm rounded-lg flex flex-col justify-between hover:bg-surface-container transition-colors shadow-sm">
      <div className="flex items-center justify-between text-outline">
        <span className="font-label-mono-xs text-label-mono-xs uppercase tracking-wider">{label}</span>
        <span className={`material-symbols-outlined text-[15px] ${tone}`}>{icon}</span>
      </div>
      <div className="mt-space-xs flex items-baseline gap-space-xs">
        <span className={`font-headline-sm text-headline-sm font-semibold ${tone}`}>{value}</span>
      </div>
      <span className="font-label-mono-xs text-label-mono-xs text-outline font-mono">{caption}</span>
    </div>
  );
}
