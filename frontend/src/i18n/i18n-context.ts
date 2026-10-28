import { createContext } from 'react';
import type { InterpolationValues, Locale, MessageKey } from './types';

export interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /** Translate a message. ``values`` fills its ``{placeholders}``. */
  t: (key: MessageKey, values?: InterpolationValues) => string;
  formatDateTime: (value: string | null | undefined, fallback?: string) => string;
  formatTime: (value: string | null | undefined, fallback?: string) => string;
  /** Wall-clock time without seconds, for an appointment rather than a timestamp. */
  formatClock: (value: string | null | undefined, fallback?: string) => string;
  formatDate: (value: string | null | undefined, fallback?: string) => string;
  /** A day heading: weekday and date, for grouping a calendar by day. */
  formatDay: (value: string | null | undefined, fallback?: string) => string;
  formatRelative: (value: string | null | undefined, fallback?: string) => string;
  formatNumber: (value: number) => string;
}

export const I18nContext = createContext<I18nValue | null>(null);
