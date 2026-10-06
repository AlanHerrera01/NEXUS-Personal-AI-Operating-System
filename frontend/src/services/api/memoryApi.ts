import { apiClient } from './apiClient';
import type { Memory, MemoryType, MemoryImportance } from '../../types';

export const memoryApi = {
  // List memories
  listMemories: async () => {
    return apiClient.get<Memory[]>('/api/v1/memories');
  },

  // Search memories
  searchMemories: async (query: string) => {
    return apiClient.post<Memory[]>('/api/v1/memories/search', { query });
  },

  // Get memory by ID
  getMemory: async (id: string) => {
    return apiClient.get<Memory>(`/api/v1/memories/${id}`);
  },

  // Save memory
  saveMemory: async (content: string, memoryType: MemoryType, importance: MemoryImportance) => {
    return apiClient.post<Memory>('/api/v1/memories', {
      content,
      memory_type: memoryType,
      importance,
    });
  },

  // Delete memory
  deleteMemory: async (id: string) => {
    return apiClient.delete(`/api/v1/memories/${id}`);
  },

  // Clear all memories
  clearMemories: async () => {
    return apiClient.delete('/api/v1/memories');
  },
};
