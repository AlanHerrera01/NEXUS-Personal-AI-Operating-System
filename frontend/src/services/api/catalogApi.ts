import { apiClient } from './apiClient';
import type { SkillView, ToolView } from '../../types';

interface SkillsResponse {
  skills: SkillView[];
}

interface ToolsResponse {
  tools: ToolView[];
}

/**
 * The public skill and tool catalog.
 *
 * These routes expose metadata only -- never credentials, secrets or internals --
 * and are not agent-scoped, so every caller sees the same catalog.
 */
export const catalogApi = {
  listSkills: () => apiClient.get<SkillsResponse>('/api/v1/skills').then((r) => r.skills),
  listTools: () => apiClient.get<ToolsResponse>('/api/v1/tools').then((r) => r.tools),
};
