import { useI18n } from '../../hooks/useI18n';
import type { Locale } from '../../i18n/types';

const LOCALES: Locale[] = ['es', 'en'];

/**
 * The language of the interface, in the frame rather than only in Settings.
 *
 * Someone who cannot read the current language has to be able to leave it from
 * wherever they already are. A switch that lives two clicks inside a screen
 * whose labels are the problem is not a switch.
 */
export function LanguageSwitch() {
  const { locale, setLocale, t } = useI18n();

  return (
    <div
      role="group"
      aria-label={t('shell.topbar.language')}
      title={t('shell.topbar.language')}
      className="hidden md:flex items-center gap-0.5 bg-surface-container-low rounded px-space-xs py-0.5"
    >
      <span className="material-symbols-outlined text-[15px] text-outline">language</span>
      {LOCALES.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLocale(code)}
          aria-pressed={locale === code}
          className={[
            'font-label-mono-xs text-label-mono-xs uppercase px-1.5 py-0.5 rounded transition-colors',
            locale === code
              ? 'bg-surface-container-high text-on-surface font-medium'
              : 'text-outline hover:text-on-surface-variant',
          ].join(' ')}
        >
          {code}
        </button>
      ))}
    </div>
  );
}
