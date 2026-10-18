import { apiClient } from './apiClient';
import type { MCPServer } from '../../types';

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
 * MCP server registration.
 *
 * Registering is configuration only: the backend stores what is sent and opens
 * no connection, so this API cannot be used to make NEXUS run a server -- only
 * to tell it which ones exist. Nothing in the tool pipeline consumes these rows
 * yet.
 */
export const mcpApi = {
  list: () => apiClient.get<MCPServersResponse>('/api/v1/mcp-servers'),

  register: (input: MCPServerInput) =>
    apiClient.post<MCPServer>('/api/v1/mcp-servers', input),

  update: (serverId: string, changes: MCPServerUpdate) =>
    apiClient.patch<MCPServer>(`/api/v1/mcp-servers/${serverId}`, changes),

  remove: (serverId: string) => apiClient.delete<void>(`/api/v1/mcp-servers/${serverId}`),
};
