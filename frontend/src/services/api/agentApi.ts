import { apiClient } from './apiClient';
import type {
  Agent,
  AgentRunResponse,
  AgentsResponse,
  AgentStatus,
  PermissionDecision,
} from '../../types';

/**
 * Agents and their runs.
 *
 * Two shapes share the `/api/v1/agents` prefix and are worth keeping apart. The
 * *registry* is an agent (`GET`/`POST /api/v1/agents`, `PATCH /api/v1/agents/{id}`).
 * A *run* is created under an agent (`POST /api/v1/agents/{agent_id}/runs`) and
 * then addressed by its own id (`/api/v1/agents/runs/{run_id}`); there is
 * deliberately no "list every run" route, because the dashboard surfaces the
 * caller's active runs through `/api/v1/overview` instead.
 *
 * The registry is what makes the rest reachable: a run needs an agent to belong
 * to, so without one the objective bar has nothing to execute against.
 */
export const agentApi = {
  listAgents: () => apiClient.get<AgentsResponse>('/api/v1/agents'),

  createAgent: (name: string, description: string) =>
    apiClient.post<Agent>('/api/v1/agents', { name, description }),

  /**
   * Activation is exclusive server-side: activating one agent stands the
   * caller's others down, so "the active agent" stays a single thing.
   */
  updateAgent: (
    agentId: string,
    changes: { name?: string; description?: string; status?: AgentStatus },
  ) => apiClient.patch<Agent>(`/api/v1/agents/${agentId}`, changes),

  createRun: (agentId: string, input: string) =>
    apiClient.post<AgentRunResponse>(`/api/v1/agents/${agentId}/runs`, { input }),

  getRun: (runId: string) =>
    apiClient.get<AgentRunResponse>(`/api/v1/agents/runs/${runId}`),

  // Resuming answers the ASK the run is parked on. `ALLOW` lets the pending
  // action execute; `DENY` lets the run observe the refusal and finish.
  resumeRun: (runId: string, permission: PermissionDecision) =>
    apiClient.post<AgentRunResponse>(`/api/v1/agents/runs/${runId}/resume`, { permission }),
};
