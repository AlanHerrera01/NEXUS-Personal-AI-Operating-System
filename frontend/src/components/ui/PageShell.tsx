import type { ReactNode } from 'react';
import { useI18n } from '../../hooks/useI18n';

interface PageShellProps {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function PageShell({ eyebrow, title, description, actions, children }: PageShellProps) {
  return (
    <div className="px-space-lg py-space-md flex flex-col gap-space-lg max-w-[1720px] mx-auto w-full">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md pb-space-xs">
        <div>
          <div className="flex items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-secondary tracking-widest uppercase">
            <span className="inline-block w-2 h-2 rounded-full bg-secondary" />
            <span>{eyebrow}</span>
          </div>
          <h1 className="font-headline-lg text-headline-lg font-semibold text-on-surface tracking-tight mt-0.5">
            {title}
          </h1>
          <p className="font-body-md text-body-md text-on-surface-variant">{description}</p>
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}

interface ComingSoonProps {
  icon: string;
  title: string;
  description: string;
}

export function ComingSoon({ icon, title, description }: ComingSoonProps) {
  const { t } = useI18n();
  return (
    <div className="bg-surface-container-low border border-outline-variant/30 rounded p-space-xl flex flex-col items-center text-center gap-space-sm">
      <div className="w-12 h-12 rounded bg-surface-container-high flex items-center justify-center text-primary">
        <span className="material-symbols-outlined text-[24px]">{icon}</span>
      </div>
      <h2 className="font-headline-sm text-headline-sm font-semibold text-on-surface">{title}</h2>
      <p className="font-body-sm text-body-sm text-on-surface-variant max-w-md">{description}</p>
      <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider bg-surface-container-lowest px-2 py-0.5 rounded mt-space-xs">
        {t('common.comingSoon')}
      </span>
    </div>
  );
}

/** Shared status rows so every data-backed page reports loading/error/empty alike. */
export function LoadingRow({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="font-label-mono-xs text-label-mono-xs text-outline bg-surface-container-lowest rounded p-space-md flex items-center gap-space-sm">
      <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse" />
      {label ?? t('common.loading')}
    </div>
  );
}

export function ErrorRow({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="bg-error-container/30 border border-error/40 rounded p-space-md flex items-center justify-between gap-space-md">
      <div className="flex items-center gap-space-sm text-error">
        <span className="material-symbols-outlined text-[18px]">cloud_off</span>
        <span className="font-body-sm text-body-sm">{message}</span>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="font-label-mono-xs text-label-mono-xs bg-surface-container hover:bg-surface-container-high text-on-surface px-space-sm py-1 rounded transition-colors"
        >
          {t('common.retry')}
        </button>
      )}
    </div>
  );
}

export function EmptyRow({ message }: { message: string }) {
  return (
    <div className="font-body-sm text-body-sm text-on-surface-variant bg-surface-container-lowest rounded p-space-md text-center">
      {message}
    </div>
  );
}

/** A bordered surface panel matching the dashboard card language. */
export function Panel({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`bg-surface-container-low border border-outline-variant/20 rounded p-space-md shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}
