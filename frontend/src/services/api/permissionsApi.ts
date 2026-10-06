import { apiClient } from './apiClient';
import type { Permission, PermissionRequest } from '../../types';

export const permissionsApi = {
  // List permissions
  listPermissions: async () => {
    return apiClient.get<Permission[]>('/api/v1/permissions');
  },

  // Create permission
  createPermission: async (data: {
    agent_id: string;
    skill_name: string;
    action_name: string;
    scope: string;
    effect: string;
    risk_level: string;
  }) => {
    return apiClient.post<Permission>('/api/v1/permissions', data);
  },

  // Delete permission
  deletePermission: async (permissionId: string) => {
    return apiClient.delete(`/api/v1/permissions/${permissionId}`);
  },

  // Get permission requests for a run
  getPermissionRequests: async (runId: string) => {
    return apiClient.get<PermissionRequest[]>(`/api/v1/agent-runs/${runId}/permission-requests`);
  },

  // Approve permission request
  approveRequest: async (runId: string, requestId: string) => {
    return apiClient.post<PermissionRequest>(
      `/api/v1/agent-runs/${runId}/permission-requests/${requestId}/approve`,
      {}
    );
  },

  // Reject permission request
  rejectRequest: async (runId: string, requestId: string) => {
    return apiClient.post<PermissionRequest>(
      `/api/v1/agent-runs/${runId}/permission-requests/${requestId}/reject`,
      {}
    );
  },
};
