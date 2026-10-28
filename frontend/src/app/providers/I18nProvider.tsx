import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { I18nContext, type I18nValue } from '../../i18n/i18n-context';
import {
  formatClock,
  formatDate,
  formatDateTime,
  formatDay,
  formatNumber,
  formatRelative,
  formatTime,
  translate,
} from '../../i18n/translate';
import type { Locale } from '../../i18n/types';

const STORAGE_KEY = 'nexus.locale';

function isLocale(value: string | null): value is Locale {
  return value === 'es' || value === 'en';
}

/**
 * The language of the first paint, before anyone has chosen one.
 *
 * The browser's own preference first, then Spanish. Spanish is not a fallback
 * chosen for being convenient: it is the language the interface was written in,
 * so a browser that states no preference gets the strings that were written
 * rather than a translation nobody has read.
 */
function initialLocale(): Locale {
  if (typeof window === 'undefined') return 'es';
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (isLocale(stored)) return stored;
  return window.navigator.language?.toLowerCase().startsWith('en') ? 'en' : 'es';
}

/**
 * Owns the interface language for the whole app.
 *
 * The choice is kept in the browser rather than in the runtime settings store:
 * it is a property of this reader, not of the deployment, and sending it to the
 * backend would publish "who reads which language" for no gain. The settings
 * panel therefore offers the same switch but does not persist it server-side.
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(initialLocale);

  const choose = useCallback((next: Locale) => {
    setLocale(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  // The lang attribute is what a screen reader and the browser's own language
  // tools read. Left at the document default, Spanish content would be spelled
  // and read aloud as English.
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      setLocale: choose,
      t: (key, values) => translate(locale, key, values),
      formatDateTime: (input, fallback) => formatDateTime(locale, input, fallback),
      formatTime: (input, fallback) => formatTime(locale, input, fallback),
      formatClock: (input, fallback) => formatClock(locale, input, fallback),
      formatDate: (input, fallback) => formatDate(locale, input, fallback),
      formatDay: (input, fallback) => formatDay(locale, input, fallback),
      formatRelative: (input, fallback) => formatRelative(locale, input, fallback),
      formatNumber: (input) => formatNumber(locale, input),
    }),
    [locale, choose],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
