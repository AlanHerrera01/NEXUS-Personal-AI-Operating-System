import { useLocation } from 'react-router-dom';
import { useAgentsDialog } from '../../hooks/useAgentsDialog';
import { useI18n } from '../../hooks/useI18n';
import { useOverview } from '../../hooks/useOverview';
import type { MessageKey } from '../../i18n/types';
import { LanguageSwitch } from './LanguageSwitch';

interface RouteMeta {
  path: string;
  groupKey: MessageKey;
  labelKey: MessageKey;
}

const ROUTE_META: RouteMeta[] = [
  { path: '/', groupKey: 'shell.groups.workspace', labelKey: 'shell.topbar.runtimeControl' },
  { path: '/chat', groupKey: 'shell.groups.workspace', labelKey: 'shell.nav.chat' },
  { path: '/calendar', groupKey: 'shell.groups.workspace', labelKey: 'shell.nav.calendar' },
  { path: '/activity', groupKey: 'shell.groups.workspace', labelKey: 'shell.nav.activity' },
  { path: '/memory', groupKey: 'shell.groups.workspace', labelKey: 'shell.nav.memory' },
  { path: '/runs', groupKey: 'shell.groups.workspace', labelKey: 'shell.nav.runs' },
  { path: '/tools', groupKey: 'shell.groups.configuration', labelKey: 'shell.nav.tools' },
  { path: '/skills', groupKey: 'shell.groups.configuration', labelKey: 'shell.nav.skills' },
  { path: '/permissions', groupKey: 'shell.groups.configuration', labelKey: 'shell.nav.permissions' },
  { path: '/automation', groupKey: 'shell.groups.configuration', labelKey: 'shell.nav.automation' },
  { path: '/settings', groupKey: 'shell.groups.configuration', labelKey: 'shell.nav.settings' },
];

function resolveMeta(pathname: string): RouteMeta {
  const exact = ROUTE_META.find((entry) => entry.path === pathname);
  if (exact) return exact;
  const prefix = ROUTE_META.filter(
    (entry) => entry.path !== '/' && pathname.startsWith(entry.path),
  ).sort((a, b) => b.path.length - a.path.length)[0];
  return prefix ?? ROUTE_META[0];
}

function formatUptime(seconds: number | undefined): string {
  if (seconds === undefined) return '--';
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  return `${days}d ${String(hours).padStart(2, '0')}h ${String(minutes).padStart(2, '0')}m`;
}

export function Topbar() {
  const { pathname } = useLocation();
  const { t } = useI18n();
  const meta = resolveMeta(pathname);
  const { data, connected } = useOverview();
  const { open: openAgents } = useAgentsDialog();

  const pending = data?.authorizations.pending_count ?? 0;
  const model = data?.model;
  const agent = data?.agent ?? null;
  const trust = data?.trust.default_decision ?? '--';

  return (
    <header className="fixed top-0 left-16 right-0 h-14 bg-surface/80 backdrop-blur-xl z-40 flex items-center justify-between px-space-lg shadow-rail">
      <div className="flex items-center gap-space-md">
        <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-outline">
          <span className="material-symbols-outlined text-[14px]">layers</span>
          <span className="uppercase">{t(meta.groupKey)}</span>
          <span className="text-outline-variant">/</span>
          <span className="text-on-surface uppercase">{t(meta.labelKey)}</span>
        </div>
        <div className="hidden lg:flex items-center gap-space-xs px-space-sm py-0.5 bg-surface-container-low rounded text-on-surface-variant font-label-mono-xs text-label-mono-xs">
          <span
            className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-secondary' : 'bg-error'}`}
          />
          <span>
            {model ? `${model.model} · ${model.provider}` : t('shell.topbar.modelUnavailable')}
            {model && !model.configured ? ` · ${t('shell.topbar.noCredentials')}` : ''}
          </span>
          {data && (
            <>
              <span className="text-outline-variant">·</span>
              <span>{t('shell.topbar.uptime', { value: formatUptime(data.system.uptime_seconds) })}</span>
            </>
          )}
        </div>
        {/* The agent everything else runs against. Reachable from every screen
            so "no active agent" is never a dead end. */}
        <button
          type="button"
          onClick={openAgents}
          title={t('shell.topbar.openAgents')}
          className="flex items-center gap-space-xs px-space-sm py-0.5 bg-surface-container-low rounded font-label-mono-xs text-label-mono-xs hover:bg-surface-container transition-colors"
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${agent ? 'bg-tertiary' : 'bg-error'}`}
          />
          <span className="text-on-surface-variant max-w-[180px] truncate">
            {agent ? t('shell.topbar.activeAgent', { name: agent.name }) : t('shell.topbar.noActiveAgent')}
          </span>
          <span className="material-symbols-outlined text-[14px] text-outline">expand_more</span>
        </button>
      </div>

      <div className="flex items-center gap-space-md">
        <div className="hidden md:flex items-center gap-space-xs px-space-sm py-0.5 bg-surface-container-low rounded font-label-mono-xs text-label-mono-xs text-primary">
          <span className="material-symbols-outlined text-[14px] text-primary">security</span>
          <span>{t('shell.topbar.trust', { decision: trust })}</span>
        </div>
        <LanguageSwitch />
        <button type="button" title="Cerrar sesión" aria-label="Cerrar sesión"
          onClick={() => window.dispatchEvent(new Event('nexus:unauthorized'))}
          className="text-outline hover:text-on-surface">
          <span className="material-symbols-outlined text-[18px]">logout</span>
        </button>
        <div className="hidden md:flex items-center gap-space-sm bg-surface-container-low px-space-sm py-1 rounded text-on-surface-variant cursor-pointer hover:bg-surface-container hover:text-on-surface transition-colors">
          <span className="material-symbols-outlined text-[15px]">search</span>
          <span className="font-body-sm text-body-sm text-outline">{t('shell.topbar.quickActions')}</span>
          <kbd className="font-label-mono-xs text-label-mono-xs bg-surface-container px-1 py-0.5 rounded text-on-surface-variant">
            ⌘K
          </kbd>
        </div>
        <div className="flex items-center gap-space-xs px-space-sm py-1 bg-surface-container-low rounded cursor-pointer hover:bg-surface-container transition-colors">
          <span
            className={`material-symbols-outlined text-[16px] ${
              pending > 0 ? 'text-error' : 'text-secondary'
            }`}
          >
            notifications
          </span>
          <span
            className={`font-label-mono-xs text-label-mono-xs bg-surface-container px-1.5 py-0.5 rounded font-medium ${
              pending > 0 ? 'text-error' : 'text-secondary'
            }`}
          >
            {t('shell.topbar.pending', { count: pending })}
          </span>
        </div>
        <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center cursor-pointer">
          <span className="material-symbols-outlined text-on-primary text-[18px]">person</span>
        </div>
      </div>
    </header>
  );
}
