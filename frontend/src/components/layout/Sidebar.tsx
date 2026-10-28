import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useI18n } from '../../hooks/useI18n';
import type { MessageKey } from '../../i18n/types';

interface NavItem {
  to: string;
  labelKey: MessageKey;
  icon: string;
  end?: boolean;
}

const WORKSPACE_NAV: NavItem[] = [
  { to: '/', labelKey: 'shell.nav.overview', icon: 'grid_view', end: true },
  { to: '/chat', labelKey: 'shell.nav.chat', icon: 'forum' },
  { to: '/calendar', labelKey: 'shell.nav.calendar', icon: 'calendar_month' },
  { to: '/activity', labelKey: 'shell.nav.activity', icon: 'monitoring' },
  { to: '/memory', labelKey: 'shell.nav.memory', icon: 'neurology' },
  { to: '/runs', labelKey: 'shell.nav.runs', icon: 'schema' },
];

const CONFIG_NAV: NavItem[] = [
  { to: '/tools', labelKey: 'shell.nav.tools', icon: 'construction' },
  { to: '/skills', labelKey: 'shell.nav.skills', icon: 'psychology' },
  { to: '/permissions', labelKey: 'shell.nav.permissions', icon: 'verified_user' },
  { to: '/automation', labelKey: 'shell.nav.automation', icon: 'bolt' },
  { to: '/settings', labelKey: 'shell.nav.settings', icon: 'settings' },
];

/* The routes carry a key rather than a label so the list stays a module
   constant: translating at render is what lets the switch change the sidebar
   without rebuilding it. */
function NavGroup({ titleKey, items, expanded }: { titleKey: MessageKey; items: NavItem[]; expanded: boolean }) {
  const { t } = useI18n();
  return (
    <div className="mt-space-md px-space-md">
      {expanded && (
        <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider font-semibold block mb-space-xs px-space-xs">
          {t(titleKey)}
        </span>
      )}
      <nav className="flex flex-col gap-0.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            title={t(item.labelKey)}
            className={({ isActive }) =>
              [
                'flex items-center justify-center px-space-sm py-space-xs rounded transition-colors group',
                expanded ? 'gap-space-sm' : '',
                isActive
                  ? 'bg-surface-container-high text-on-surface font-medium'
                  : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface',
              ].join(' ')
            }
          >
            <span className="material-symbols-outlined text-[16px]">{item.icon}</span>
            {expanded && <span className="font-body-sm text-body-sm">{t(item.labelKey)}</span>}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function Sidebar() {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  return (
    <aside
      className={`fixed left-0 top-0 h-screen bg-surface-container-lowest z-50 flex flex-col justify-between shadow-rail transition-all duration-300 group ${
        expanded ? 'w-64' : 'w-16'
      }`}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >
      <div className="flex flex-col">
        <div className="px-space-md pt-space-md pb-space-sm flex items-center justify-between">
          <div className="flex items-center gap-space-sm">
            <div className="w-7 h-7 rounded bg-surface-container-high flex items-center justify-center text-primary flex-shrink-0">
              <span className="material-symbols-outlined text-[18px]">deployed_code</span>
            </div>
            {expanded && (
              <div className="flex flex-col">
                <span className="font-headline-sm text-headline-sm font-semibold tracking-tight text-on-surface leading-tight">
                  {t('shell.app.name')}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                  {t('shell.app.version')}
                </span>
              </div>
            )}
          </div>
          {expanded && (
            <span className="font-label-mono-xs text-label-mono-xs bg-surface-container px-space-xs py-0.5 rounded text-secondary flex-shrink-0">
              {t('shell.app.running')}
            </span>
          )}
        </div>

        <div className="px-space-md py-space-xs">
          <div className="w-full flex items-center justify-between px-space-sm py-space-xs bg-surface-container-low rounded text-on-surface hover:bg-surface-container transition-colors cursor-pointer">
            <div className="flex items-center gap-space-xs">
              <span className="material-symbols-outlined text-secondary text-[16px] flex-shrink-0">terminal</span>
              {expanded && (
                <span className="font-body-sm text-body-sm text-on-surface font-medium truncate">
                  {t('shell.app.workspace')}
                </span>
              )}
            </div>
            {expanded && (
              <span className="material-symbols-outlined text-on-surface-variant text-[16px] flex-shrink-0">
                unfold_more
              </span>
            )}
          </div>
        </div>

        <NavGroup titleKey="shell.groups.workspace" items={WORKSPACE_NAV} expanded={expanded} />
        <NavGroup titleKey="shell.groups.configuration" items={CONFIG_NAV} expanded={expanded} />
      </div>

      <div className="p-space-md bg-surface-container-lowest">
        <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-space-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-tertiary flex-shrink-0" />
              {expanded && (
                <span className="font-body-sm text-body-sm text-on-surface font-medium">
                  {t('shell.sidebar.localUser')}
                </span>
              )}
            </div>
            <span className="material-symbols-outlined text-tertiary text-[16px] flex-shrink-0">shield</span>
          </div>
          {expanded && (
            <div className="flex items-center justify-between text-on-surface-variant">
              <span className="font-label-mono-xs text-label-mono-xs">
                {t('shell.sidebar.trustEngine')}
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-tertiary">
                {t('shell.sidebar.active')}
              </span>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
