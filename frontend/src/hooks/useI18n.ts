import { useContext } from 'react';
import { I18nContext, type I18nValue } from '../i18n/i18n-context';

/**
 * The interface language, its translator and the locale-aware formatters.
 *
 * Every user-facing string goes through ``t``; every date, time and number goes
 * through one of the formatters, so a screen cannot end up in one language with
 * another language's dates on it.
 */
export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (value === null) {
    throw new Error('useI18n must be used within an I18nProvider');
  }
  return value;
}
