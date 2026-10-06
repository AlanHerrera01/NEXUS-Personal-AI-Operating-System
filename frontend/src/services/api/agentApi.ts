import { apiClient } from './apiClient';
import type { AgentRun, AgentAction } from '../../types';

export const agentApi = {
  // Create agent run
  createRun: async (request: string) => {
    return apiClient.post<{ id: string }>('/api/v1/agent-runs', { user_request: request });
  },

  // Get agent run
  getRun: async (runId: string) => {
    return apiClient.get<AgentRun>(`/api/v1/agent-runs/${runId}`);
  },

  // List agent runs
  listRuns: async () => {
    return apiClient.get<AgentRun[]>('/api/v1/agent-runs');
  },

  // Resume agent run (approve/reject)
  resumeRun: async (runId: string, allow: boolean) => {
    return apiClient.post<{ response: string }>(`/api/v1/agent-runs/${runId}/resume`, { allow });
  },

  // Get agent actions for a run
  getActions: async (runId: string) => {
    return apiClient.get<AgentAction[]>(`/api/v1/agent-runs/${runId}/actions`);
  },
};
