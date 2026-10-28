import { messages } from './messages';
import type { InterpolationValues, Locale, MessageKey, Messages } from './types';

/** Anything the pages pass to a formatter: an ISO string, or nothing at all. */
export type DateInput = string | null | undefined;

function lookup(tree: Messages, key: string): string | undefined {
  let node: unknown = tree;
  for (const part of key.split('.')) {
    if (typeof node !== 'object' || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === 'string' ? node : undefined;
}

function interpolate(template: string, values?: InterpolationValues): string {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.hasOwn(values, name) ? String(values[name]) : match,
  );
}

export function translate(
  locale: Locale,
  key: MessageKey,
  values?: InterpolationValues,
): string {
  // The English tree is typed from the Spanish one, so a gap here cannot
  // compile. The fallbacks exist for one case only: a key that reached this
  // function through a value TypeScript never saw, where rendering the key
  // itself is more honest than rendering an empty button.
  const template = lookup(messages[locale], key) ?? lookup(messages.es, key) ?? key;
  return interpolate(template, values);
}

function toDate(value: DateInput): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(locale: Locale, value: DateInput, fallback = '--'): string {
  const date = toDate(value);
  if (date === null) return fallback;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'medium' }).format(
    date,
  );
}

export function formatTime(locale: Locale, value: DateInput, fallback = '--'): string {
  const date = toDate(value);
  if (date === null) return fallback;
  return new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

export function formatDate(locale: Locale, value: DateInput, fallback = '--'): string {
  const date = toDate(value);
  if (date === null) return fallback;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'short' }).format(date);
}

/**
 * Wall-clock time without seconds: what an appointment needs and no more.
 *
 * ``formatTime`` carries seconds because it is used where an exact instant
 * matters (an audit timestamp). An event that starts at 20:50 reading
 * "20:50:00" invents a precision the event does not have.
 */
export function formatClock(locale: Locale, value: DateInput, fallback = '--'): string {
  const date = toDate(value);
  if (date === null) return fallback;
  return new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

/** A calendar day heading: the weekday and the date, in the reader's language. */
export function formatDay(locale: Locale, value: DateInput, fallback = '--'): string {
  const date = toDate(value);
  if (date === null) return fallback;
  return new Intl.DateTimeFormat(locale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(date);
}

export function formatNumber(locale: Locale, value: number): string {
  return new Intl.NumberFormat(locale).format(value);
}

/**
 * How long ago something happened, in the reader's language.
 *
 * ``Intl`` rather than a template with a translated prefix: the unit names and
 * the word order differ between languages, and "hace 2 min" against
 * "2 min ago" is exactly the kind of thing a hand-rolled prefix gets wrong in
 * the language nobody on the project reads.
 */
export function formatRelative(locale: Locale, value: DateInput, fallback = '--'): string {
  const date = toDate(value);
  if (date === null) return fallback;
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  let amount = seconds;
  let unit: Intl.RelativeTimeFormatUnit = 'second';
  if (seconds >= 86_400) {
    amount = Math.round(seconds / 86_400);
    unit = 'day';
  } else if (seconds >= 3_600) {
    amount = Math.round(seconds / 3_600);
    unit = 'hour';
  } else if (seconds >= 60) {
    amount = Math.round(seconds / 60);
    unit = 'minute';
  }
  return new Intl.RelativeTimeFormat(locale, { numeric: 'always', style: 'narrow' }).format(
    -amount,
    unit,
  );
}
