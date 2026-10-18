import { apiClient } from './apiClient';
import type { RuntimeSettings, RuntimeSettingsUpdate } from '../../types';

/**
 * Runtime settings exposed by the backend.
 *
 * `GET` returns the effective configuration plus provenance (which fields carry
 * a saved override and what they fall back to). `PATCH` changes only the safe
 * subset -- the model and its generation parameters -- and the backend refuses
 * to expose the API key, the base URL or the trust posture as writable.
 */
export const settingsApi = {
  get: () => apiClient.get<RuntimeSettings>('/api/v1/settings'),

  update: (changes: RuntimeSettingsUpdate) =>
    apiClient.patch<RuntimeSettings>('/api/v1/settings', changes),
};
