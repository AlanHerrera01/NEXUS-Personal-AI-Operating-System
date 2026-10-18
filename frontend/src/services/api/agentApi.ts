import { apiClient } from './apiClient';
import type { AgentRunResponse, PermissionDecision } from '../../types';

/**
 * Agent run endpoints.
 *
 * Note the shape: a run is created *under an agent*
 * (`POST /api/v1/agents/{agent_id}/runs`) and then addressed by its own id
 * (`/api/v1/agents/runs/{run_id}`). There is deliberately no "list every run"
 * route -- the dashboard surfaces the caller's active runs through
 * `/api/v1/overview` instead.
 */
export const agentApi = {
  createRun: (agentId: string, input: string) =>
    apiClient.post<AgentRunResponse>(`/api/v1/agents/${agentId}/runs`, { input }),

  getRun: (runId: string) =>
    apiClient.get<AgentRunResponse>(`/api/v1/agents/runs/${runId}`),

  // Resuming answers the ASK the run is parked on. `ALLOW` lets the pending
  // action execute; `DENY` lets the run observe the refusal and finish.
  resumeRun: (runId: string, permission: PermissionDecision) =>
    apiClient.post<AgentRunResponse>(`/api/v1/agents/runs/${runId}/resume`, { permission }),
};
