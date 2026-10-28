import type { messages } from './messages';

/** The languages the interface ships. Adding one is adding a branch in `messages`. */
export type Locale = keyof typeof messages;

/** Spanish is the reference tree: every other language is typed from it. */
export type Messages = (typeof messages)['es'];

/**
 * Every dotted path that resolves to a string, e.g. ``'chat.placeholder'``.
 *
 * Derived from the dictionary rather than declared by hand, so a call to
 * ``t('chat.placeholer')`` does not compile and a Spanish string added without
 * its English pair breaks the build instead of surfacing as a mixed-language
 * screen that nobody notices until a reader outside the project does.
 */
export type MessageKey = Path<Messages>;

type Path<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${Path<T[K]>}`;
}[keyof T & string];

/** Values substituted into the ``{placeholders}`` of a message. */
export type InterpolationValues = Record<string, string | number>;
