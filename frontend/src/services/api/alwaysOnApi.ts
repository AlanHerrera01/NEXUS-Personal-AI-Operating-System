import { apiClient } from './apiClient';
import type {
  CreateProactiveRule,
  CreateScheduledJob,
  JobExecution,
  ProactiveRule,
  ScheduledJob,
  ScheduledJobStatus,
  UpdateScheduledJob,
} from '../../types';

const JOBS = '/api/v1/scheduled-jobs';
const RULES = '/api/v1/proactive-rules';

export const alwaysOnApi = {
  // Scheduled jobs
  listJobs: async (status?: ScheduledJobStatus) => {
    const query = status ? `?status=${status}` : '';
    return apiClient.get<ScheduledJob[]>(`${JOBS}${query}`);
  },

  getJob: async (jobId: string) => {
    return apiClient.get<ScheduledJob>(`${JOBS}/${jobId}`);
  },

  createJob: async (data: CreateScheduledJob) => {
    return apiClient.post<ScheduledJob>(JOBS, data);
  },

  updateJob: async (jobId: string, data: UpdateScheduledJob) => {
    return apiClient.patch<ScheduledJob>(`${JOBS}/${jobId}`, data);
  },

  pauseJob: async (jobId: string) => {
    return apiClient.post<ScheduledJob>(`${JOBS}/${jobId}/pause`, {});
  },

  resumeJob: async (jobId: string) => {
    return apiClient.post<ScheduledJob>(`${JOBS}/${jobId}/resume`, {});
  },

  // Deletes the job and returns the final state, so the UI can drop it without
  // a second round trip.
  deleteJob: async (jobId: string) => {
    return apiClient.delete<ScheduledJob>(`${JOBS}/${jobId}`);
  },

  listExecutions: async (jobId: string, limit = 50) => {
    return apiClient.get<JobExecution[]>(`${JOBS}/${jobId}/executions?limit=${limit}`);
  },

  getExecution: async (executionId: string) => {
    return apiClient.get<JobExecution>(`${JOBS}/executions/${executionId}`);
  },

  // Proactive rules
  listRules: async (enabledOnly = false) => {
    const query = enabledOnly ? '?enabled_only=true' : '';
    return apiClient.get<ProactiveRule[]>(`${RULES}${query}`);
  },

  getRule: async (ruleId: string) => {
    return apiClient.get<ProactiveRule>(`${RULES}/${ruleId}`);
  },

  createRule: async (data: CreateProactiveRule) => {
    return apiClient.post<ProactiveRule>(RULES, data);
  },

  // Enable/disable are separate endpoints rather than a PATCH, so the backend can
  // treat them as the explicit state transition they are.
  enableRule: async (ruleId: string) => {
    return apiClient.post<ProactiveRule>(`${RULES}/${ruleId}/enable`, {});
  },

  disableRule: async (ruleId: string) => {
    return apiClient.post<ProactiveRule>(`${RULES}/${ruleId}/disable`, {});
  },

  deleteRule: async (ruleId: string) => {
    return apiClient.delete<void>(`${RULES}/${ruleId}`);
  },
};