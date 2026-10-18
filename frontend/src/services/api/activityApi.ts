import { apiClient } from './apiClient';
import type { ActivityFeed, ActivityWindow } from '../../types';

/**
 * `GET /api/v1/activity` -- the merged, owner-scoped audit feed.
 *
 * One request returns the timeline plus the summary the telemetry cockpit
 * renders. The backend degrades source-by-source when the database is down, so
 * a response with an empty list and `storage_available: false` is still valid.
 */
export const activityApi = {
  get: (window: ActivityWindow = '24h', limit = 100) =>
    apiClient.get<ActivityFeed>(`/api/v1/activity?window=${window}&limit=${limit}`),
};
