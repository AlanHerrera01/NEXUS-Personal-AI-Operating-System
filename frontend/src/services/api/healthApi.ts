import { apiClient } from './apiClient';
import type { HealthResponse, LLMHealthResponse, RuntimeHealth } from '../../types';

/** Liveness and dependency probes exposed by the backend. */
export const healthApi = {
  // `GET /api/v1/health` reports the service, its phase and the database state.
  get: () => apiClient.get<HealthResponse>('/api/v1/health'),

  // `GET /api/v1/health/llm` reports whether the model provider is configured.
  llm: () => apiClient.get<LLMHealthResponse>('/api/v1/health/llm'),

  // `GET /api/v1/runtime/health` reports the sandbox provider, if any.
  runtime: () => apiClient.get<RuntimeHealth>('/api/v1/runtime/health'),
};
