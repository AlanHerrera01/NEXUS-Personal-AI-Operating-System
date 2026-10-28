import { useState } from 'react';
import { useI18n } from '../../hooks/useI18n';
import { useOverview } from '../../hooks/useOverview';
import { useAsyncData } from '../../hooks/useAsyncData';
import { agentApi } from '../../services/api/agentApi';
import { ApiError } from '../../services/api/apiClient';
import type { Agent, AgentsResponse } from '../../types';

/**
 * Create an agent, or switch which one is active.
 *
 * This exists because the objective bar, the runs page and the permissions page
 * all act on the dashboard's active agent, and there was no way to create one --
 * a fresh deployment had nothing to execute against. Registration here is a real
 * write to the backend; the list and the create form both go through the API.
 *
 * Activation is exclusive on the server, so choosing an agent stands the others
 * down. The dialog says so rather than leaving the operator to wonder why the
 * previous agent went inactive.
 */
export function AgentsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const { refresh } = useOverview();
  const agents = useAsyncData(
    () =>
      open
        ? agentApi.listAgents()
        : Promise.resolve<AgentsResponse>({ items: [], active_id: null }),
    [open],
  );

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const items = agents.data?.items ?? [];
  const activeId = agents.data?.active_id ?? null;

  const settle = () => {
    agents.reload();
    // The dashboard polls every few seconds, but this makes the change visible
    // at once: the objective bar reads its agent from the same payload.
    refresh();
  };

  const create = async () => {
    const trimmed = name.trim();
    if (trimmed === '' || busy !== null) return;
    setBusy('create');
    setError(null);
    try {
      await agentApi.createAgent(trimmed, description.trim());
      setName('');
      setDescription('');
      settle();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('shell.dialogs.agents.createFailed'));
    } finally {
      setBusy(null);
    }
  };

  const activate = async (agent: Agent) => {
    if (busy !== null) return;
    setBusy(agent.id);
    setError(null);
    try {
      await agentApi.updateAgent(agent.id, { status: 'ACTIVE' });
      settle();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : t('shell.dialogs.agents.activateFailed'),
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-surface-container-lowest/80 backdrop-blur-md flex items-center justify-center p-space-md"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-xl max-h-[88vh] overflow-y-auto rounded-xl bg-surface-container-low shadow-2xl p-space-lg flex flex-col gap-space-md"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between pb-space-sm">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary-container/20 flex items-center justify-center text-primary">
              <span className="material-symbols-outlined text-[20px]">smart_toy</span>
            </div>
            <div>
              <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                {t('shell.dialogs.agents.title')}
              </h2>
              <p className="font-body-sm text-body-sm text-on-surface-variant">
                {t('shell.dialogs.agents.subtitle')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-outline hover:text-on-surface hover:bg-surface-container transition-colors"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="p-space-md rounded-lg bg-surface-container-lowest flex items-start gap-2">
          <span className="material-symbols-outlined text-[18px] text-secondary">info</span>
          <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
            {t('shell.dialogs.agents.explanation')}
          </p>
        </div>

        {/* Registry */}
        <div className="flex flex-col gap-1.5">
          <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
            {t('shell.dialogs.agents.registered')}
          </span>
          {agents.loading ? (
            <span className="font-body-sm text-body-sm text-outline">
              {t('shell.dialogs.agents.loading')}
            </span>
          ) : agents.error ? (
            <span className="font-body-sm text-body-sm text-error" role="alert">
              {agents.error}
            </span>
          ) : items.length === 0 ? (
            <span className="font-body-sm text-body-sm text-outline">
              {t('shell.dialogs.agents.empty')}
            </span>
          ) : (
            items.map((agent) => {
              const isActive = agent.id === activeId;
              return (
                <div
                  key={agent.id}
                  className="flex items-center justify-between gap-space-sm p-space-sm rounded-lg bg-surface-container-lowest"
                >
                  <div className="min-w-0 flex flex-col">
                    <div className="flex items-center gap-2">
                      <span className="font-body-sm text-body-sm text-on-surface font-medium truncate">
                        {agent.name}
                      </span>
                      {/* The agent's status is the backend's own value. */}
                      <span
                        className={`font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded ${
                          isActive
                            ? 'bg-tertiary/15 text-tertiary'
                            : 'bg-surface-container text-outline'
                        }`}
                      >
                        {agent.status}
                      </span>
                    </div>
                    {agent.description && (
                      <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                        {agent.description}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    disabled={isActive || busy !== null}
                    onClick={() => void activate(agent)}
                    className="px-space-sm py-1 rounded bg-surface-container text-on-surface font-label-mono-xs text-label-mono-xs font-semibold hover:bg-surface-container-high disabled:opacity-40 transition-colors whitespace-nowrap"
                  >
                    {isActive
                      ? t('shell.dialogs.agents.active')
                      : busy === agent.id
                        ? t('shell.dialogs.agents.activating')
                        : t('shell.dialogs.agents.activate')}
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Create */}
        <div className="flex flex-col gap-space-sm pt-space-sm border-t border-outline-variant/20">
          <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
            {t('shell.dialogs.agents.newAgent')}
          </span>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-space-sm">
            <label className="flex flex-col gap-1">
              <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                {t('common.name')}
              </span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="NEXUS"
                className="bg-surface-container-lowest rounded-lg px-space-sm py-2 font-body-sm text-body-sm text-on-surface placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/40"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-label-mono-xs text-label-mono-xs uppercase text-outline">
                {t('common.description')}
              </span>
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder={t('shell.dialogs.agents.descriptionPlaceholder')}
                className="bg-surface-container-lowest rounded-lg px-space-sm py-2 font-body-sm text-body-sm text-on-surface placeholder:text-outline outline-none focus:ring-1 focus:ring-primary/40"
              />
            </label>
          </div>

          {error && (
            <p className="font-body-sm text-body-sm text-error" role="alert">
              {error}
            </p>
          )}

          <div className="flex items-center justify-end">
            <button
              type="button"
              disabled={name.trim() === '' || busy !== null}
              onClick={() => void create()}
              className="px-space-md py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50 transition-all flex items-center gap-1"
            >
              <span className="material-symbols-outlined text-[16px]">add</span>
              {busy === 'create'
                ? t('shell.dialogs.agents.creating')
                : t('shell.dialogs.agents.create')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
