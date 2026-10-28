import { apiClient } from './apiClient';
import type { AgentRunResponse } from '../../types';

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface CreateConversationRequest {
  title: string;
}

export const conversationApi = {
  list: (): Promise<Conversation[]> =>
    apiClient.get<Conversation[]>('/api/v1/conversations'),

  get: (id: string): Promise<Conversation> =>
    apiClient.get<Conversation>(`/api/v1/conversations/${id}`),

  // The conversation's runs, oldest first: everything needed to rebuild the
  // thread when a chat is reopened from the sidebar.
  listRuns: (id: string): Promise<AgentRunResponse[]> =>
    apiClient.get<AgentRunResponse[]>(`/api/v1/conversations/${id}/runs`),

  create: (data: CreateConversationRequest): Promise<Conversation> =>
    apiClient.post<Conversation>('/api/v1/conversations', data),

  delete: (id: string): Promise<void> =>
    apiClient.delete<void>(`/api/v1/conversations/${id}`),
};
