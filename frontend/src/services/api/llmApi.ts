import { apiClient } from './apiClient';
import type { LLMGenerateResponse } from '../../types';

/**
 * Direct model access (`POST /api/v1/llm/generate`).
 *
 * This is the plain completion path -- no tools, no memory, no trust decisions.
 * Anything the agent should *do* goes through an agent run instead, because that
 * path is what the Trust Engine governs.
 */
export const llmApi = {
  generate: (message: string) =>
    apiClient.post<LLMGenerateResponse>('/api/v1/llm/generate', { message }),
};
