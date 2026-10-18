import { apiClient } from './apiClient';
import type {
  MemoryDecisionResponse,
  MemoryDetail,
  MemoryImportance,
  MemoryListResponse,
  MemoryType,
} from '../../types';

export type MemorySource = 'USER_EXPLICIT' | 'AGENT_ACTION' | 'CONVERSATION' | 'SYSTEM';
export type MemoryPersistence = 'SAVE' | 'DO_NOT_SAVE';

export interface SaveMemoryInput {
  agent_id: string;
  content: string;
  memory_type: MemoryType;
  source: MemorySource;
  importance?: MemoryImportance;
  requested_persistence?: MemoryPersistence;
  user_instruction?: string;
}

/**
 * Memory is scoped to an agent, so every read and write carries `agent_id`.
 * Omitting it is a 422 on the backend rather than a broader query -- memory is
 * never "all agents at once".
 */
export const memoryApi = {
  listMemories: (agentId: string, limit = 100) =>
    apiClient
      .get<MemoryListResponse>(`/api/v1/memories?agent_id=${agentId}&limit=${limit}`)
      .then((r) => r.items),

  searchMemories: (agentId: string, query: string, limit = 10) =>
    apiClient
      .post<MemoryListResponse>('/api/v1/memories/search', { agent_id: agentId, query, limit })
      .then((r) => r.items),

  getMemory: (memoryId: string, agentId: string) =>
    apiClient.get<MemoryDetail>(`/api/v1/memories/${memoryId}?agent_id=${agentId}`),

  saveMemory: (input: SaveMemoryInput) =>
    apiClient.post<MemoryDecisionResponse>('/api/v1/memories', {
      ...input,
      importance: input.importance ?? 'MEDIUM',
    }),

  deleteMemory: (memoryId: string, agentId: string) =>
    apiClient.delete<void>(`/api/v1/memories/${memoryId}?agent_id=${agentId}`),

  clearMemories: (agentId: string) =>
    apiClient.delete<{ deleted: number }>(`/api/v1/memories?agent_id=${agentId}`),
};
