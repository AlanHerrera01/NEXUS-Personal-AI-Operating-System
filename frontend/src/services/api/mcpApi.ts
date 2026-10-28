import { apiClient } from './apiClient';
import type { MCPConnectionTest, MCPServer } from '../../types';

/** Transports an operator may register from the panel. */
export type RegistrableTransport = 'stdio' | 'sse' | 'streamable_http';

export interface MCPServerInput {
  name: string;
  description: string;
  transport_type: RegistrableTransport;
  /** stdio: the executable. sse/streamable_http: the URL. */
  endpoint: string;
  /** Transport-specific extras, stored verbatim by the backend. */
  configuration: Record<string, unknown>;
}

export interface MCPServerUpdate {
  description?: string;
  enabled?: boolean;
  configuration?: Record<string, unknown>;
}

export interface MCPServersResponse {
  items: MCPServer[];
  transports: string[];
  registered: number;
}

/**
 * MCP server registration and connection testing.
 *
 * Registration writes configuration. `test` opens a real connection and returns
 * the tools the server exposes; the same discovery runs before an agent plans.
 * Every discovered tool is MEDIUM risk and needs confirmation, so this API
 * cannot execute one.
 */
export const mcpApi = {
  list: () => apiClient.get<MCPServersResponse>('/api/v1/mcp-servers'),

  register: (input: MCPServerInput) =>
    apiClient.post<MCPServer>('/api/v1/mcp-servers', input),

  update: (serverId: string, changes: MCPServerUpdate) =>
    apiClient.patch<MCPServer>(`/api/v1/mcp-servers/${serverId}`, changes),

  test: (serverId: string) =>
    apiClient.post<MCPConnectionTest>(`/api/v1/mcp-servers/${serverId}/test`),

  remove: (serverId: string) => apiClient.delete<void>(`/api/v1/mcp-servers/${serverId}`),
};
