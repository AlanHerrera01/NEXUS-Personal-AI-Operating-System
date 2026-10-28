import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAsyncData } from '../hooks/useAsyncData';
import { useI18n } from '../hooks/useI18n';
import { calendarApi } from '../services/api/calendarApi';
import { EmptyRow, ErrorRow, LoadingRow } from '../components/ui/PageShell';
import type { MessageKey } from '../i18n/types';
import type { CalendarEvent } from '../types';

type CalendarWindow = 'upcoming' | 'today' | 'next7d' | 'all';

const WINDOW_CHIPS: { key: CalendarWindow; labelKey: MessageKey }[] = [
  { key: 'upcoming', labelKey: 'pages.calendar.windows.upcoming' },
  { key: 'today', labelKey: 'pages.calendar.windows.today' },
  { key: 'next7d', labelKey: 'pages.calendar.windows.next7d' },
  { key: 'all', labelKey: 'pages.calendar.windows.all' },
];

const DAY_MS = 86_400_000;

/** Stable empty list: ``data ?? []`` would allocate a new array every render and
 *  make the memos below recompute on each one. */
const NO_EVENTS: CalendarEvent[] = [];

/** The local calendar day an instant falls on, as a stable grouping key. */
function localDayKey(value: string): string {
  return localDayKeyFromDate(new Date(value));
}

function localDayKeyFromDate(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

/** How far away a day is, counted in whole local days. */
function dayOffset(value: string, reference: Date): number {
  const start = new Date(value);
  const a = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const b = new Date(reference.getFullYear(), reference.getMonth(), reference.getDate());
  return Math.round((a.getTime() - b.getTime()) / DAY_MS);
}

type EventPhase = 'live' | 'scheduled' | 'ended';

function eventPhase(event: CalendarEvent, now: number): EventPhase {
  if (Date.parse(event.end_at) < now) return 'ended';
  if (Date.parse(event.start_at) <= now) return 'live';
  return 'scheduled';
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** Case- and accent-insensitive, so "reunion" still finds "Reunión". */
function searchable(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase();
}

/** The viewer's own offset, shown rather than assumed. */
function timezoneLabel(date: Date): string {
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '-';
  const absolute = Math.abs(offset);
  const hours = Math.floor(absolute / 60);
  const minutes = absolute % 60;
  return `UTC${sign}${hours}${minutes === 0 ? '' : `:${String(minutes).padStart(2, '0')}`}`;
}

export default function Calendar() {
  const {
    t,
    locale,
    formatClock,
    formatDay,
    formatNumber,
    formatRelative,
  } = useI18n();
  const [window, setWindow] = useState<CalendarWindow>('upcoming');
  const [refreshKey, setRefreshKey] = useState(0);
  const [query, setQuery] = useState('');
  const [selectedDay, setSelectedDay] = useState<Date | null>(null);
  const [monthCursor, setMonthCursor] = useState(() => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth(), 1);
  });
  const [toastDismissedFor, setToastDismissedFor] = useState(-1);
  const [toastExpiredFor, setToastExpiredFor] = useState(-1);

  const events = useAsyncData(() => calendarApi.listEvents({ limit: 200 }), [refreshKey]);
  const items = useMemo(() => events.data ?? NO_EVENTS, [events.data]);
  // Read once per refresh rather than on every render: "now" moves, and reading
  // it during render is what makes a window filter drift under the reader.
  const [now, setNow] = useState(() => Date.now());

  const refresh = () => {
    setNow(Date.now());
    setRefreshKey((key) => key + 1);
  };

  /* The toast belongs to a refresh the reader asked for, not to the first read:
     a banner on page load would claim a sync nobody performed. Visibility is
     derived from that refresh settling, so no effect has to mirror it. */
  const toastOpen =
    refreshKey > 0 &&
    !events.loading &&
    !events.error &&
    toastDismissedFor !== refreshKey &&
    toastExpiredFor !== refreshKey;

  useEffect(() => {
    if (!toastOpen) return;
    const timer = globalThis.setTimeout(() => setToastExpiredFor(refreshKey), 4500);
    return () => globalThis.clearTimeout(timer);
  }, [toastOpen, refreshKey]);

  const selectedKey = selectedDay ? localDayKeyFromDate(selectedDay) : null;
  const search = searchable(query.trim());

  const upcoming = useMemo(
    () =>
      items
        .filter((event) => Date.parse(event.end_at) >= now)
        .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at)),
    [items, now],
  );
  const nextEvent = upcoming[0] ?? null;
  const reference = new Date(now);
  const todayKey = localDayKeyFromDate(reference);

  const visible = (() => {
    let list: CalendarEvent[];
    switch (window) {
      case 'today':
        list = items.filter((event) => localDayKey(event.start_at) === todayKey);
        break;
      case 'next7d':
        list = items.filter(
          (event) =>
            Date.parse(event.end_at) >= now &&
            Date.parse(event.start_at) <= now + 7 * DAY_MS,
        );
        break;
      case 'all':
        list = items;
        break;
      default:
        list = items.filter((event) => Date.parse(event.end_at) >= now);
    }
    if (selectedKey) list = list.filter((event) => localDayKey(event.start_at) === selectedKey);
    if (search) {
      list = list.filter((event) =>
        searchable(
          `${event.title} ${event.description} ${event.location ?? ''}`,
        ).includes(search),
      );
    }
    return list;
  })();

  /* Grouped by local day, preserving the backend's ascending order, so the page
     reads as an agenda rather than a table sorted by an invisible column. */
  const groups = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const event of visible) {
      const key = localDayKey(event.start_at);
      const bucket = map.get(key);
      if (bucket) bucket.push(event);
      else map.set(key, [event]);
    }
    return Array.from(map.values());
  }, [visible]);

  /* Every event per day, for the month dots: the widget shows the month's
     shape, so it counts the whole calendar rather than the active filter. */
  const eventCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const event of items) {
      const key = localDayKey(event.start_at);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [items]);

  const weekly = useMemo(() => {
    const limit = now + 7 * DAY_MS;
    const weekEvents = items.filter(
      (event) => Date.parse(event.end_at) >= now && Date.parse(event.start_at) <= limit,
    );
    let minutes = 0;
    for (const event of weekEvents) {
      minutes += Math.max(0, (Date.parse(event.end_at) - Date.parse(event.start_at)) / 60_000);
    }
    return {
      hours: minutes / 60,
      days: new Set(weekEvents.map((event) => localDayKey(event.start_at))).size,
    };
  }, [items, now]);

  const monthCells = useMemo(() => {
    const year = monthCursor.getFullYear();
    const month = monthCursor.getMonth();
    const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7; // Monday first
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const total = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
    return Array.from({ length: total }, (_, index) => {
      const date = new Date(year, month, 1 - firstWeekday + index);
      return { date, inMonth: date.getMonth() === month };
    });
  }, [monthCursor]);

  const monthTitle = useMemo(
    () =>
      capitalize(
        new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(monthCursor),
      ),
    [locale, monthCursor],
  );

  const weekdayLabels = useMemo(() => {
    const monday = new Date(2024, 0, 1); // A known Monday, so the week starts on LU.
    return Array.from({ length: 7 }, (_, index) => {
      const date = new Date(monday);
      date.setDate(monday.getDate() + index);
      return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(date).toUpperCase();
    });
  }, [locale]);

  const timezone = useMemo(() => timezoneLabel(new Date(now)), [now]);

  const duration = (event: CalendarEvent): string => {
    const minutes = Math.max(
      0,
      Math.round((Date.parse(event.end_at) - Date.parse(event.start_at)) / 60_000),
    );
    if (minutes < 60) return t('pages.calendar.duration.minutes', { minutes });
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return rest === 0
      ? t('pages.calendar.duration.hours', { hours })
      : t('pages.calendar.duration.hoursMinutes', { hours, minutes: rest });
  };

  const dayLabel = (event: CalendarEvent): string => {
    const offset = dayOffset(event.start_at, reference);
    if (offset === 0) return t('pages.calendar.day.today');
    if (offset === 1) return t('pages.calendar.day.tomorrow');
    return formatDay(event.start_at);
  };

  const chooseWindow = (next: CalendarWindow) => {
    setWindow(next);
    setSelectedDay(null);
  };

  const chooseDay = (date: Date) => {
    const key = localDayKeyFromDate(date);
    if (selectedKey === key) {
      setSelectedDay(null);
      return;
    }
    if (
      date.getMonth() !== monthCursor.getMonth() ||
      date.getFullYear() !== monthCursor.getFullYear()
    ) {
      setMonthCursor(new Date(date.getFullYear(), date.getMonth(), 1));
    }
    setWindow('all');
    setSelectedDay(date);
  };

  const weeklyHours = Math.round(weekly.hours * 10) / 10;
  const weeklyDaysText =
    weekly.days === 1
      ? t('pages.calendar.metrics.weeklyDaysOne', { count: weekly.days })
      : t('pages.calendar.metrics.weeklyDaysOther', { count: weekly.days });
  const weeklyBar = Math.min(100, Math.round((weekly.days / 7) * 100));

  return (
    <div className="px-space-lg py-space-md flex flex-col gap-space-lg max-w-[1720px] mx-auto w-full">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-start justify-between gap-space-md pb-space-sm">
        <div className="flex flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-space-xs font-label-mono-xs text-label-mono-xs text-secondary tracking-widest uppercase">
            <span className="inline-block w-2 h-2 rounded-full bg-secondary animate-pulse" />
            <span>{t('pages.calendar.header.eyebrow')}</span>
            <span className="text-outline-variant">/</span>
            <span className="text-on-surface-variant font-medium">
              {t('pages.calendar.header.section')}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-space-md mt-1">
            <h1 className="font-headline-xl text-headline-xl font-bold tracking-tight text-on-surface">
              {t('pages.calendar.header.title')}
            </h1>
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container-high text-tertiary font-label-mono-xs text-label-mono-xs">
              <span className="material-symbols-outlined text-[13px] text-tertiary">
                verified_user
              </span>
              <span>{t('pages.calendar.header.governed')}</span>
            </div>
          </div>
          <p className="font-body-md text-body-md text-on-surface-variant max-w-4xl mt-1">
            {t('pages.calendar.header.description')}
          </p>
        </div>

        <div className="flex items-center gap-space-xs self-start xl:self-auto shrink-0">
          <button
            type="button"
            onClick={refresh}
            disabled={events.loading}
            className="flex items-center gap-1.5 px-space-sm py-1.5 rounded bg-surface-container-high text-on-surface font-body-sm text-body-sm hover:bg-surface-bright transition-colors disabled:opacity-60"
          >
            <span
              className={`material-symbols-outlined text-[16px] text-secondary ${
                events.loading ? 'animate-spin' : ''
              }`}
            >
              sync
            </span>
            <span>
              {events.loading
                ? t('pages.calendar.actions.refreshing')
                : t('pages.calendar.actions.refresh')}
            </span>
          </button>
          <Link
            to="/chat"
            title={t('pages.calendar.actions.requestHint')}
            className="flex items-center gap-1.5 px-space-md py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-fixed-dim transition-all active:scale-[0.99] shadow-sm"
          >
            <span className="material-symbols-outlined text-[16px]">add_task</span>
            <span>{t('pages.calendar.actions.requestEvent')}</span>
          </Link>
        </div>
      </div>

      {/* Telemetry row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-space-sm">
        <div className="flex flex-col justify-between gap-space-sm p-space-md rounded bg-surface-container-low border border-outline-variant/20 hover:bg-surface-container transition-colors">
          <div className="flex items-center justify-between">
            <span className="font-label-mono-xs text-label-mono-xs text-outline tracking-wider uppercase font-semibold">
              {t('pages.calendar.metrics.upcoming')}
            </span>
            <span className="material-symbols-outlined text-primary text-[18px]">
              calendar_today
            </span>
          </div>
          <div className="flex items-baseline gap-space-xs">
            <span className="font-headline-lg text-headline-lg font-bold text-on-surface">
              {formatNumber(upcoming.length)}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              {upcoming.length === 1
                ? t('pages.calendar.metrics.confirmedOne', { count: upcoming.length })
                : t('pages.calendar.metrics.confirmedOther', { count: upcoming.length })}
            </span>
          </div>
          <div className="font-label-mono-xs text-label-mono-xs text-tertiary flex items-center gap-1">
            <span className="w-1 h-1 rounded-full bg-tertiary" />
            <span>{t('pages.calendar.metrics.validated')}</span>
          </div>
        </div>

        <div className="flex flex-col justify-between gap-space-sm p-space-md rounded bg-surface-container-low border border-outline-variant/20 hover:bg-surface-container transition-colors">
          <div className="flex items-center justify-between">
            <span className="font-label-mono-xs text-label-mono-xs text-outline tracking-wider uppercase font-semibold">
              {t('pages.calendar.metrics.today')}
            </span>
            <span className="material-symbols-outlined text-secondary text-[18px]">alarm</span>
          </div>
          <div className="flex flex-col">
            {nextEvent ? (
              <>
                <span className="font-body-md text-body-md font-semibold text-on-surface truncate">
                  {nextEvent.title}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-secondary font-medium truncate">
                  {formatDay(nextEvent.start_at)} · {formatClock(nextEvent.start_at)}
                </span>
              </>
            ) : (
              <>
                <span className="font-body-md text-body-md font-semibold text-on-surface-variant">
                  {t('pages.calendar.metrics.noNext')}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {t('pages.calendar.metrics.noNextHint')}
                </span>
              </>
            )}
          </div>
          <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant truncate">
            {t('pages.calendar.metrics.todayHint')}
          </span>
        </div>

        <div className="flex flex-col justify-between gap-space-sm p-space-md rounded bg-surface-container-low border border-outline-variant/20 hover:bg-surface-container transition-colors">
          <div className="flex items-center justify-between">
            <span className="font-label-mono-xs text-label-mono-xs text-outline tracking-wider uppercase font-semibold">
              {t('pages.calendar.metrics.integration')}
            </span>
            <span className="material-symbols-outlined text-tertiary text-[18px]">hub</span>
          </div>
          <div className="flex flex-col">
            <span className="font-body-md text-body-md font-semibold text-on-surface truncate">
              {t('pages.calendar.metrics.integrationName')}
            </span>
            <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
              {t('pages.calendar.metrics.integrationDetail')}
            </span>
          </div>
          <div className="font-label-mono-xs text-label-mono-xs text-secondary flex items-center gap-1">
            <span className="material-symbols-outlined text-[12px]">lock</span>
            <span className="truncate">{t('pages.calendar.metrics.integrationNote')}</span>
          </div>
        </div>

        <div className="flex flex-col justify-between gap-space-sm p-space-md rounded bg-surface-container-low border border-outline-variant/20 hover:bg-surface-container transition-colors">
          <div className="flex items-center justify-between">
            <span className="font-label-mono-xs text-label-mono-xs text-outline tracking-wider uppercase font-semibold">
              {t('pages.calendar.metrics.weekly')}
            </span>
            <span className="material-symbols-outlined text-on-surface-variant text-[18px]">
              hourglass_top
            </span>
          </div>
          <div className="flex items-baseline gap-space-xs">
            <span className="font-headline-lg text-headline-lg font-bold text-on-surface">
              {formatNumber(weeklyHours)}
            </span>
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              {t('pages.calendar.metrics.weeklyUnit')}
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <div className="w-full bg-surface-container-highest rounded-full h-1 overflow-hidden">
              <div className="bg-primary h-full" style={{ width: `${weeklyBar}%` }} />
            </div>
            <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
              {weekly.days === 0 ? t('pages.calendar.metrics.weeklyEmpty') : weeklyDaysText}
            </span>
          </div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center justify-between gap-space-sm bg-surface-container-lowest p-space-xs rounded">
        <div className="flex flex-wrap items-center gap-1">
          {WINDOW_CHIPS.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={() => chooseWindow(chip.key)}
              className={`px-space-sm py-1 rounded font-body-sm text-body-sm transition-all ${
                window === chip.key
                  ? 'bg-primary text-on-primary font-medium'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container'
              }`}
            >
              {t(chip.labelKey)}
              {chip.key === 'upcoming' && (
                <span
                  className={`ml-1 font-code-base font-normal ${
                    window === chip.key ? 'text-on-primary/80' : 'text-outline'
                  }`}
                >
                  {formatNumber(upcoming.length)}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-space-xs pr-1">
          <div className="flex items-center gap-1.5 px-space-sm py-1 rounded bg-surface-container-low text-on-surface-variant">
            <span className="material-symbols-outlined text-[15px] text-outline">search</span>
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('pages.calendar.search.placeholder')}
              aria-label={t('pages.calendar.search.placeholder')}
              className="bg-transparent text-body-sm font-body-sm text-on-surface placeholder-outline focus:outline-none w-32 md:w-44"
            />
            {query !== '' && (
              <button
                type="button"
                onClick={() => setQuery('')}
                aria-label={t('pages.calendar.actions.clearSearch')}
                className="text-on-surface-variant hover:text-on-surface transition-colors"
              >
                <span className="material-symbols-outlined text-[14px]">close</span>
              </button>
            )}
          </div>
          <span
            title={t('pages.calendar.mini.timezone')}
            className="hidden sm:flex items-center gap-1 px-2 py-1 rounded bg-surface-container-low font-label-mono-xs text-label-mono-xs text-outline"
          >
            <span className="material-symbols-outlined text-[13px]">public</span>
            {timezone}
          </span>
        </div>
      </div>

      {selectedDay && (
        <div className="flex items-center justify-between gap-space-sm px-space-sm py-1.5 rounded bg-secondary/10 text-secondary">
          <span className="font-label-mono-xs text-label-mono-xs flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[14px]">event</span>
            {t('pages.calendar.search.selectedDay', {
              day: formatDay(selectedDay.toISOString()),
            })}
          </span>
          <button
            type="button"
            onClick={() => setSelectedDay(null)}
            className="font-label-mono-xs text-label-mono-xs hover:text-on-surface transition-colors"
          >
            {t('pages.calendar.search.clearDay')}
          </button>
        </div>
      )}

      {/* Main split pane */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md items-start">
        <div className="lg:col-span-8 flex flex-col gap-space-md">
          {events.loading && <LoadingRow label={t('pages.calendar.states.loading')} />}
          {events.error && (
            <ErrorRow message={t('pages.calendar.states.error')} onRetry={refresh} />
          )}
          {!events.loading && !events.error && groups.length === 0 && (
            <EmptyRow
              message={
                search
                  ? t('pages.calendar.search.noMatch')
                  : t('pages.calendar.states.empty')
              }
            />
          )}

          {groups.map((bucket) => {
            const offset = dayOffset(bucket[0].start_at, reference);
            return (
              <section
                key={localDayKey(bucket[0].start_at)}
                className="flex flex-col gap-space-xs"
              >
                <div className="flex items-center justify-between px-space-xs py-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-label-mono-sm text-label-mono-sm font-bold text-secondary tracking-wider uppercase">
                      {dayLabel(bucket[0])}
                    </span>
                    <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
                    {(offset === 0 || offset === 1) && (
                      <span className="font-label-mono-xs text-label-mono-xs text-outline">
                        {formatDay(bucket[0].start_at)}
                      </span>
                    )}
                  </div>
                  <span className="font-label-mono-xs text-label-mono-xs bg-surface-container-low text-on-surface-variant px-1.5 py-0.5 rounded font-mono">
                    {formatNumber(bucket.length)}
                  </span>
                </div>

                <div className="flex flex-col gap-space-xs">
                  {bucket.map((event) => {
                    const phase = eventPhase(event, now);
                    const phaseTone =
                      phase === 'live'
                        ? 'text-secondary'
                        : phase === 'ended'
                          ? 'text-outline'
                          : 'text-tertiary';
                    const barTone =
                      phase === 'live'
                        ? 'bg-secondary'
                        : phase === 'ended'
                          ? 'bg-outline-variant'
                          : 'bg-primary';
                    const phaseLabel =
                      phase === 'live'
                        ? t('pages.calendar.status.live')
                        : phase === 'ended'
                          ? t('pages.calendar.status.ended')
                          : t('pages.calendar.status.scheduled');

                    return (
                      <article
                        key={event.id}
                        className="group relative flex flex-col md:flex-row items-start md:items-center justify-between gap-space-sm p-space-md rounded bg-surface-container-low border border-outline-variant/20 hover:bg-surface-container transition-all"
                      >
                        <div className="flex items-start md:items-center gap-space-md min-w-0">
                          <div className="flex flex-col items-start md:items-end w-16 shrink-0 font-code-base text-code-base">
                            <span className="font-semibold text-on-surface">
                              {formatClock(event.start_at)}
                            </span>
                            <span className="text-label-mono-xs font-label-mono-xs text-outline">
                              {formatClock(event.end_at)}
                            </span>
                          </div>
                          <div
                            className={`w-0.5 min-h-[2.5rem] self-stretch rounded hidden md:block ${barTone}`}
                          />
                          <div className="flex flex-col min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="font-headline-sm text-headline-sm font-semibold text-on-surface group-hover:text-secondary transition-colors">
                                {event.title}
                              </h3>
                              <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant whitespace-nowrap">
                                {duration(event)}
                              </span>
                            </div>

                            {event.location && (
                              <span className="font-body-sm text-body-sm text-on-surface-variant flex items-center gap-1 mt-0.5">
                                <span className="material-symbols-outlined text-[14px]">place</span>
                                {event.location}
                              </span>
                            )}
                            {event.description && (
                              <span className="font-body-sm text-body-sm text-on-surface-variant line-clamp-2 mt-0.5">
                                {event.description}
                              </span>
                            )}

                            <div className="flex flex-wrap items-center gap-space-xs mt-1">
                              <span className="font-body-sm text-body-sm text-outline">
                                {t('pages.calendar.event.created', {
                                  when: formatRelative(event.created_at),
                                })}
                              </span>
                              <span className="text-outline-variant font-mono">·</span>
                              <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container text-secondary flex items-center gap-1">
                                <span className="material-symbols-outlined text-[11px]">
                                  terminal
                                </span>
                                {t('pages.calendar.event.skill')}
                              </span>
                              <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-tertiary/10 text-tertiary flex items-center gap-1">
                                <span className="w-1 h-1 rounded-full bg-tertiary" />
                                {t('pages.calendar.event.readOnly')}
                              </span>
                              {event.agent_id && (
                                <span className="font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary flex items-center gap-1">
                                  <span className="material-symbols-outlined text-[11px]">
                                    fingerprint
                                  </span>
                                  {t('pages.calendar.event.agent')} ·{' '}
                                  <span className="font-code-base">
                                    {event.agent_id.slice(0, 8)}
                                  </span>
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        <div className="mt-space-sm md:mt-0 flex items-center gap-space-sm self-end md:self-center shrink-0">
                          <span
                            className={`font-label-mono-xs text-label-mono-xs uppercase tracking-wider font-semibold ${phaseTone}`}
                          >
                            {phaseLabel}
                          </span>
                          <span className="material-symbols-outlined text-outline group-hover:text-on-surface text-[18px]">
                            chevron_right
                          </span>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>

        <div className="lg:col-span-4 flex flex-col gap-space-md">
          {/* Month widget */}
          <div className="p-space-md rounded bg-surface-container-low border border-outline-variant/20 flex flex-col gap-space-sm">
            <div className="flex items-center justify-between pb-space-xs gap-space-sm">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-body-md text-body-md font-semibold text-on-surface truncate">
                  {monthTitle}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-secondary bg-surface-container px-1 py-0.5 rounded whitespace-nowrap">
                  {timezone}
                </span>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  aria-label={t('pages.calendar.mini.prevMonth')}
                  onClick={() =>
                    setMonthCursor(
                      new Date(monthCursor.getFullYear(), monthCursor.getMonth() - 1, 1),
                    )
                  }
                  className="p-1 rounded hover:bg-surface-container text-on-surface-variant hover:text-on-surface transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px]">chevron_left</span>
                </button>
                <button
                  type="button"
                  aria-label={t('pages.calendar.mini.nextMonth')}
                  onClick={() =>
                    setMonthCursor(
                      new Date(monthCursor.getFullYear(), monthCursor.getMonth() + 1, 1),
                    )
                  }
                  className="p-1 rounded hover:bg-surface-container text-on-surface-variant hover:text-on-surface transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px]">chevron_right</span>
                </button>
              </div>
            </div>

            <div className="grid grid-cols-7 gap-1 text-center font-label-mono-xs text-label-mono-xs text-outline pb-1">
              {weekdayLabels.map((label) => (
                <span key={label}>{label}</span>
              ))}
            </div>

            <div className="grid grid-cols-7 gap-1 text-center font-code-base text-code-base">
              {monthCells.map(({ date, inMonth }) => {
                const key = localDayKeyFromDate(date);
                const count = eventCounts.get(key) ?? 0;
                const isSelected = selectedKey === key;
                const isToday = key === todayKey;
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => chooseDay(date)}
                    aria-pressed={isSelected}
                    aria-label={formatDay(date.toISOString())}
                    className={[
                      'relative py-1 rounded text-body-sm transition-colors flex flex-col items-center justify-center',
                      isSelected
                        ? 'bg-secondary/15 text-secondary font-bold'
                        : inMonth
                          ? 'text-on-surface-variant hover:bg-surface-container'
                          : 'text-outline-variant/50 hover:bg-surface-container/50',
                      !isSelected && isToday ? 'text-secondary font-semibold' : '',
                    ].join(' ')}
                  >
                    <span>{date.getDate()}</span>
                    {count > 0 && (
                      <span
                        className={`w-1 h-1 rounded-full absolute bottom-0.5 ${
                          isSelected ? 'bg-secondary' : 'bg-primary'
                        }`}
                      />
                    )}
                  </button>
                );
              })}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-1 pt-space-xs font-label-mono-xs text-label-mono-xs text-outline">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                {t('pages.calendar.mini.legendEvents')}
              </span>
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
                {t('pages.calendar.mini.legendToday')}
              </span>
              {selectedDay && (
                <button
                  type="button"
                  onClick={() => setSelectedDay(null)}
                  className="hover:text-on-surface transition-colors"
                >
                  {t('pages.calendar.search.clearDay')}
                </button>
              )}
            </div>
          </div>

          {/* Governance panel */}
          <div className="p-space-md rounded bg-surface-container-low border border-outline-variant/20 flex flex-col gap-space-sm">
            <div className="flex items-center justify-between pb-space-xs gap-space-sm">
              <div className="flex items-center gap-2 min-w-0">
                <span className="material-symbols-outlined text-[16px] text-tertiary">shield</span>
                <span className="font-body-md text-body-md font-semibold text-on-surface truncate">
                  {t('pages.calendar.governance.title')}
                </span>
              </div>
              <span className="font-label-mono-xs text-label-mono-xs bg-tertiary/10 text-tertiary px-1.5 py-0.5 rounded font-mono whitespace-nowrap">
                {t('pages.calendar.governance.enforced')}
              </span>
            </div>

            <p className="font-body-sm text-body-sm text-on-surface-variant">
              {t('pages.calendar.governance.intro')}
            </p>

            <div className="flex flex-col gap-space-xs mt-1">
              <div className="p-space-sm rounded bg-surface-container flex items-center justify-between gap-space-sm">
                <div className="flex flex-col min-w-0">
                  <span className="font-code-base text-code-base font-semibold text-on-surface truncate">
                    calendar.list_events
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                    {t('pages.calendar.governance.listEventsNote')}
                  </span>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-tertiary/10 text-tertiary font-bold flex items-center gap-1 whitespace-nowrap">
                  <span className="w-1 h-1 rounded-full bg-tertiary" />
                  {t('pages.calendar.governance.allow')}
                </span>
              </div>

              <div className="p-space-sm rounded bg-surface-container flex items-center justify-between gap-space-sm">
                <div className="flex flex-col min-w-0">
                  <span className="font-code-base text-code-base font-semibold text-on-surface truncate">
                    calendar.create_event
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                    {t('pages.calendar.governance.createEventNote')}
                  </span>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-secondary/10 text-secondary font-bold flex items-center gap-1 whitespace-nowrap">
                  <span className="w-1 h-1 rounded-full bg-secondary" />
                  {t('pages.calendar.governance.ask')}
                </span>
              </div>

              <div className="p-space-sm rounded bg-surface-container flex items-center justify-between gap-space-sm">
                <div className="flex flex-col min-w-0">
                  <span className="font-code-base text-code-base font-semibold text-on-surface truncate">
                    {t('pages.calendar.governance.screenName')}
                  </span>
                  <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
                    {t('pages.calendar.governance.screenNote')}
                  </span>
                </div>
                <span className="font-label-mono-xs text-label-mono-xs px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-bold flex items-center gap-1 whitespace-nowrap">
                  <span className="w-1 h-1 rounded-full bg-outline" />
                  {t('pages.calendar.governance.readOnly')}
                </span>
              </div>
            </div>

            <div className="pt-space-xs flex flex-col gap-1.5">
              <Link
                to="/activity"
                className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded bg-surface-container text-secondary hover:bg-surface-container-high transition-colors font-body-sm text-body-sm"
              >
                <span className="material-symbols-outlined text-[15px]">history_edu</span>
                <span>{t('pages.calendar.governance.audit')}</span>
              </Link>
              <Link
                to="/chat"
                className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded bg-surface-container-low text-on-surface-variant hover:text-on-surface hover:bg-surface-container transition-colors font-body-sm text-body-sm"
              >
                <span className="material-symbols-outlined text-[15px]">forum</span>
                <span>{t('pages.calendar.governance.chat')}</span>
              </Link>
            </div>
          </div>

          {/* Read telemetry */}
          <div className="p-space-sm rounded bg-surface-container-lowest border border-outline-variant/10 flex items-center justify-between gap-space-sm text-on-surface-variant font-label-mono-xs text-label-mono-xs">
            <div className="flex items-center gap-1.5 min-w-0">
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${
                  events.error ? 'bg-error' : 'bg-tertiary'
                }`}
              />
              <span className="truncate">{t('pages.calendar.telemetry.source')}</span>
            </div>
            <span className="font-code-base text-outline whitespace-nowrap">
              {t('pages.calendar.telemetry.stats', {
                count: formatNumber(items.length),
                clock: formatClock(new Date(now).toISOString()),
              })}
            </span>
          </div>
        </div>
      </div>

      {/* Refresh confirmation */}
      <div
        aria-live="polite"
        className={`fixed bottom-space-lg right-space-lg max-w-md p-space-md rounded bg-surface-container-highest text-on-surface shadow-2xl flex items-center gap-space-md transition-all duration-300 z-50 ${
          toastOpen
            ? 'opacity-100 translate-y-0'
            : 'opacity-0 translate-y-4 pointer-events-none'
        }`}
      >
        <div className="w-8 h-8 rounded-full bg-tertiary/20 flex items-center justify-center text-tertiary shrink-0">
          <span className="material-symbols-outlined text-[18px]">done_all</span>
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-body-md text-body-md font-semibold">
            {t('pages.calendar.toast.title')}
          </span>
          <span className="font-label-mono-xs text-label-mono-xs text-outline truncate">
            {t('pages.calendar.toast.detail', { count: formatNumber(items.length) })}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setToastDismissedFor(refreshKey)}
          aria-label={t('pages.calendar.toast.close')}
          className="ml-auto text-on-surface-variant hover:text-on-surface"
        >
          <span className="material-symbols-outlined text-[16px]">close</span>
        </button>
      </div>
    </div>
  );
}
