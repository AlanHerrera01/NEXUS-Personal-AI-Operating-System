import { NavLink } from 'react-router-dom';

interface NavItem {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
}

const WORKSPACE_NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'grid_view', end: true },
  { to: '/chat', label: 'Chat', icon: 'forum' },
  { to: '/activity', label: 'Activity', icon: 'monitoring' },
  { to: '/memory', label: 'Memory', icon: 'neurology' },
  { to: '/runs', label: 'Runs', icon: 'schema' },
];

const CONFIG_NAV: NavItem[] = [
  { to: '/tools', label: 'Tools', icon: 'construction' },
  { to: '/skills', label: 'Skills', icon: 'psychology' },
  { to: '/permissions', label: 'Permissions', icon: 'verified_user' },
  { to: '/automation', label: 'Automation', icon: 'bolt' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
];

function NavGroup({ title, items }: { title: string; items: NavItem[] }) {
  return (
    <div className="mt-space-md px-space-md">
      <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider font-semibold block mb-space-xs px-space-xs">
        {title}
      </span>
      <nav className="flex flex-col gap-0.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              [
                'flex items-center gap-space-sm px-space-sm py-space-xs rounded transition-colors',
                isActive
                  ? 'bg-surface-container-high text-on-surface font-medium'
                  : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface',
              ].join(' ')
            }
          >
            <span className="material-symbols-outlined text-[16px]">{item.icon}</span>
            <span className="font-body-sm text-body-sm">{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-surface-container-lowest z-50 flex flex-col justify-between shadow-rail">
      <div className="flex flex-col">
        <div className="px-space-md pt-space-md pb-space-sm flex items-center justify-between">
          <div className="flex items-center gap-space-sm">
            <div className="w-7 h-7 rounded bg-surface-container-high flex items-center justify-center text-primary">
              <span className="material-symbols-outlined text-[18px]">deployed_code</span>
            </div>
            <div className="flex flex-col">
              <span className="font-headline-sm text-headline-sm font-semibold tracking-tight text-on-surface leading-tight">
                NEXUS
              </span>
              <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                v1.0-alpha · 70B
              </span>
            </div>
          </div>
          <span className="font-label-mono-xs text-label-mono-xs bg-surface-container px-space-xs py-0.5 rounded text-secondary">
            RUNNING
          </span>
        </div>

        <div className="px-space-md py-space-xs">
          <div className="w-full flex items-center justify-between px-space-sm py-space-xs bg-surface-container-low rounded text-on-surface hover:bg-surface-container transition-colors cursor-pointer">
            <div className="flex items-center gap-space-xs">
              <span className="material-symbols-outlined text-secondary text-[16px]">terminal</span>
              <span className="font-body-sm text-body-sm text-on-surface font-medium truncate">
                Personal Workspace
              </span>
            </div>
            <span className="material-symbols-outlined text-on-surface-variant text-[16px]">
              unfold_more
            </span>
          </div>
        </div>

        <NavGroup title="Workspace" items={WORKSPACE_NAV} />
        <NavGroup title="Configuration" items={CONFIG_NAV} />
      </div>

      <div className="p-space-md bg-surface-container-lowest">
        <div className="p-space-sm bg-surface-container-low rounded flex flex-col gap-space-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-space-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-tertiary" />
              <span className="font-body-sm text-body-sm text-on-surface font-medium">
                Usuario Local
              </span>
            </div>
            <span className="material-symbols-outlined text-tertiary text-[16px]">shield</span>
          </div>
          <div className="flex items-center justify-between text-on-surface-variant">
            <span className="font-label-mono-xs text-label-mono-xs">Trust Engine</span>
            <span className="font-label-mono-xs text-label-mono-xs text-tertiary">ACTIVE</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
