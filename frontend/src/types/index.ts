// Agent
export interface Agent {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

// Agent Run
export type AgentRunStatus = 
  | 'CREATED'
  | 'CONTEXT_LOADING'
  | 'PLANNING'
  | 'WAITING_PERMISSION'
  | 'EXECUTING'
  | 'OBSERVING'
  | 'COMPLETED'
  | 'FAILED'
  | 'BLOCKED'
  | 'CANCELLED';

export interface AgentRun {
  id: string;
  agent_id: string;
  user_request: string;
  status: AgentRunStatus;
  created_at: string;
  updated_at: string;
}

// Agent Action
export type AgentActionStatus = 
  | 'PROPOSED'
  | 'APPROVED'
  | 'EXECUTING'
  | 'COMPLETED'
  | 'FAILED'
  | 'BLOCKED';

export interface AgentAction {
  id: string;
  agent_run_id: string;
  skill_name: string;
  action_name: string;
  arguments: Record<string, unknown>;
  status: AgentActionStatus;
  created_at: string;
  risk_level: string;
  permission_decision: string | null;
  policy_result: string | null;
  execution_status: string | null;
  error_message: string | null;
}

// Memory
export type MemoryType = 'EPISODIC' | 'SEMANTIC' | 'PREFERENCE';
export type MemoryImportance = 'LOW' | 'MEDIUM' | 'HIGH';

export interface Memory {
  id: string;
  user_id: string;
  content: string;
  memory_type: MemoryType;
  importance: MemoryImportance;
  source: string;
  created_at: string;
  expires_at: string | null;
}

// Permission
export type PermissionDecision = 'ALLOW' | 'ASK' | 'DENY';
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export interface Permission {
  id: string;
  user_id: string;
  agent_id: string;
  skill_name: string;
  action_name: string;
  scope: string;
  effect: PermissionDecision;
  risk_level: RiskLevel;
  created_at: string;
  expires_at: string | null;
}

// Permission Request
export type PermissionRequestStatus = 
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'EXPIRED'
  | 'CANCELLED';

export interface PermissionRequest {
  id: string;
  agent_run_id: string;
  tool_name: string;
  skill_name: string;
  reason: string;
  risk_level: RiskLevel;
  arguments_summary: Record<string, unknown>;
  status: PermissionRequestStatus;
  created_at: string;
  updated_at: string;
  expires_at: string;
}

// Tool
export interface ToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  skill_name: string;
  risk_level: RiskLevel;
  read_only: boolean;
  side_effect: boolean;
  requires_confirmation: boolean;
  category: string | null;
  version: string;
  tags: string[];
  metadata?: Record<string, unknown>;
}

// Skill
export interface Skill {
  id: string;
  name: string;
  description: string;
  tools: ToolDefinition[];
}

// MCP Server
export type MCPServerStatus = 
  | 'DISCONNECTED'
  | 'CONNECTING'
  | 'READY'
  | 'ERROR'
  | 'DISABLED';

export type MCPTransportType = 
  | 'streamable_http'
  | 'stdio'
  | 'sse'
  | 'in_process';

export interface MCPServer {
  id: string;
  name: string;
  description: string;
  transport_type: MCPTransportType;
  endpoint: string;
  configuration: Record<string, unknown>;
  enabled: boolean;
  trust_level: string;
  owner_id: string | null;
  status: MCPServerStatus;
  created_at: string;
  updated_at: string;
  last_connected_at: string | null;
  metadata: Record<string, unknown>;
}

// Runtime Session
export type RuntimeStatus = 
  | 'CREATED'
  | 'INITIALIZING'
  | 'READY'
  | 'RUNNING'
  | 'WAITING'
  | 'FAILED'
  | 'STOPPING'
  | 'STOPPED'
  | 'EXPIRED'
  | 'BLOCKED';

export interface RuntimeSession {
  id: string;
  agent_run_id: string;
  status: RuntimeStatus;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
}

// Always-On: Schedules
export type ScheduledTriggerType = 'ONCE' | 'INTERVAL' | 'CRON' | 'EVENT';

export type ScheduledJobStatus =
  | 'ACTIVE'
  | 'PAUSED'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export interface ScheduledJob {
  id: string;
  user_id: string;
  agent_id: string;
  name: string;
  description: string;
  trigger_type: ScheduledTriggerType;
  timezone: string;
  cron_expression: string | null;
  interval_seconds: number | null;
  payload: Record<string, unknown>;
  status: ScheduledJobStatus;
  next_run_at: string | null;
  last_run_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export type JobExecutionStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'WAITING_PERMISSION'
  | 'COMPLETED'
  | 'FAILED'
  | 'SKIPPED'
  | 'CANCELLED';

export interface JobExecution {
  id: string;
  scheduled_job_id: string;
  agent_run_id: string | null;
  trigger_event_id: string | null;
  status: JobExecutionStatus;
  scheduled_for: string;
  attempt: number;
  result_summary: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface CreateScheduledJob {
  agent_id: string;
  name: string;
  trigger_type: ScheduledTriggerType;
  description?: string;
  timezone?: string;
  cron_expression?: string | null;
  interval_seconds?: number | null;
  run_at?: string | null;
  payload?: Record<string, unknown>;
}

export interface UpdateScheduledJob {
  name?: string;
  description?: string;
  timezone?: string;
  cron_expression?: string | null;
  interval_seconds?: number | null;
  payload?: Record<string, unknown>;
}

// Always-On: Proactive Rules
export interface ProactiveRule {
  id: string;
  user_id: string;
  agent_id: string;
  name: string;
  condition: Record<string, unknown>;
  action: Record<string, unknown>;
  enabled: boolean;
  cooldown_seconds: number;
  last_triggered_at: string | null;
  trigger_count: number;
  created_at: string;
}

export interface CreateProactiveRule {
  agent_id: string;
  name: string;
  condition: Record<string, unknown>;
  action: Record<string, unknown>;
  cooldown_seconds?: number;
  enabled?: boolean;
}

// A rule fires at most once per cooldown, so "eligible" is the useful
// question rather than "should it fire right now".
export interface ProactiveEvaluation {
  rule_id: string;
  rule_name: string;
  eligible: boolean;
  reason: string;
}
