import { apiClient } from './apiClient';
import type { Overview } from '../../types';

/**
 * The dashboard read model: `GET /api/v1/overview`.
 *
 * One request returns health, the configured model, the trust posture, the
 * caller's active runs and any authorizations waiting on them. The backend
 * degrades section-by-section rather than failing, so a partial response is
 * still a valid response.
 */
export const overviewApi = {
  get: () => apiClient.get<Overview>('/api/v1/overview'),
};
