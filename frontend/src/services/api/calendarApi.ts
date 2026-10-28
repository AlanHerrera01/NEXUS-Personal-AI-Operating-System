import { apiClient } from './apiClient';
import type { CalendarEvent } from '../../types';

/**
 * The owner's calendar, read-only.
 *
 * There is deliberately no create/delete here. Events are written by the agent
 * through the governed `calendar.create_event` tool, which passes the Trust
 * Engine; a REST write would be a second, ungoverned way into the same table.
 * Reading, which has no such concern, is all this surface offers.
 */
export const calendarApi = {
  listEvents: (params?: { start?: string; end?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.start) query.set('start', params.start);
    if (params?.end) query.set('end', params.end);
    if (params?.limit) query.set('limit', String(params.limit));
    const suffix = query.toString();
    return apiClient.get<CalendarEvent[]>(
      `/api/v1/calendar/events${suffix ? `?${suffix}` : ''}`,
    );
  },
};
