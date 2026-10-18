import { useLocation } from 'react-router-dom';
import { useOverview } from '../../hooks/useOverview';

interface RouteMeta {
  path: string;
  group: string;
  label: string;
}

const ROUTE_META: RouteMeta[] = [
  { path: '/', group: 'WORKSPACE', label: 'RUNTIME CONTROL' },
  { path: '/chat', group: 'WORKSPACE', label: 'CHAT' },
  { path: '/activity', group: 'WORKSPACE', label: 'ACTIVITY' },
  { path: '/memory', group: 'WORKSPACE', label: 'MEMORY' },
  { path: '/runs', group: 'WORKSPACE', label: 'RUNS' },
  { path: '/tools', group: 'CONFIGURATION', label: 'TOOLS' },
  { path: '/skills', group: 'CONFIGURATION', label: 'SKILLS' },
  { path: '/permissions', group: 'CONFIGURATION', label: 'PERMISSIONS' },
  { path: '/automation', group: 'CONFIGURATION', label: 'AUTOMATION' },
  { path: '/settings', group: 'CONFIGURATION', label: 'SETTINGS' },
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
  const meta = resolveMeta(pathname);
  const { data, connected } = useOverview();

  const pending = data?.authorizations.pending_count ?? 0;
  const model = data?.model;
  const trust = data?.trust.default_decision ?? '--';

  return (
    <header className="fixed top-0 left-64 right-0 h-14 bg-surface/80 backdrop-blur-xl z-40 flex items-center justify-between px-space-lg shadow-rail">
      <div className="flex items-center gap-space-md">
        <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-outline">
          <span className="material-symbols-outlined text-[14px]">layers</span>
          <span>{meta.group}</span>
          <span className="text-outline-variant">/</span>
          <span className="text-on-surface uppercase">{meta.label}</span>
        </div>
        <div className="hidden lg:flex items-center gap-space-xs px-space-sm py-0.5 bg-surface-container-low rounded text-on-surface-variant font-label-mono-xs text-label-mono-xs">
          <span
            className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-secondary' : 'bg-error'}`}
          />
          <span>
            {model ? `${model.model} · ${model.provider}` : 'Modelo no disponible'}
            {model && !model.configured ? ' · sin credenciales' : ''}
          </span>
          {data && (
            <>
              <span className="text-outline-variant">·</span>
              <span>uptime {formatUptime(data.system.uptime_seconds)}</span>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-space-md">
        <div className="hidden md:flex items-center gap-space-xs px-space-sm py-0.5 bg-surface-container-low rounded font-label-mono-xs text-label-mono-xs text-primary">
          <span className="material-symbols-outlined text-[14px] text-primary">security</span>
          <span>TRUST {trust} · Firewall v2.4</span>
        </div>
        <div className="hidden md:flex items-center gap-space-sm bg-surface-container-low px-space-sm py-1 rounded text-on-surface-variant cursor-pointer hover:bg-surface-container hover:text-on-surface transition-colors">
          <span className="material-symbols-outlined text-[15px]">search</span>
          <span className="font-body-sm text-body-sm text-outline">Quick Actions</span>
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
            {pending} Pending
          </span>
        </div>
        <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center cursor-pointer">
          <span className="material-symbols-outlined text-on-primary text-[18px]">person</span>
        </div>
      </div>
    </header>
  );
}
