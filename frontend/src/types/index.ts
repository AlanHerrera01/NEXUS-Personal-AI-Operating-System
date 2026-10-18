// Agent
export type AgentStatus = 'ACTIVE' | 'INACTIVE';

export interface Agent {
  id: string;
  name: string;
  description: string;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/agents — the caller's registry plus which one is active. */
export interface AgentsResponse {
  items: Agent[];
  /**
   * The agent the dashboard would run a quick action against — the oldest
   * ACTIVE one — or null when the caller has none active.
   */
  active_id: string | null;
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
  /** False when the transport is registered but the current adapter cannot reach it. */
  transport_supported: boolean;
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

// ---------------------------------------------------------------------------
// Backend read models (mirror app/presentation/schemas)
// ---------------------------------------------------------------------------

// GET /api/v1/overview
export interface OverviewSystemHealth {
  status: string;
  database: string;
  environment: string;
  uptime_seconds: number;
}

export interface OverviewModel {
  provider: string;
  model: string;
  configured: boolean;
}

export interface OverviewRuntime {
  available: boolean;
  provider: string;
  detail: string;
}

export interface OverviewTrust {
  default_decision: string;
  allow_grants: number;
  ask_grants: number;
  deny_grants: number;
  total_grants: number;
}

export interface OverviewRun {
  run_id: string;
  status: AgentRunStatus | string;
  user_request: string;
  created_at: string;
  updated_at: string;
}

export interface OverviewRuns {
  active_count: number;
  items: OverviewRun[];
}

export interface OverviewAuthorization {
  request_id: string;
  agent_run_id: string;
  tool_name: string;
  skill_name: string;
  reason: string;
  risk_level: RiskLevel;
  created_at: string;
  expires_at: string;
}

export interface OverviewAuthorizations {
  pending_count: number;
  items: OverviewAuthorization[];
}

export interface OverviewAgent {
  id: string;
  name: string;
}

export interface Overview {
  system: OverviewSystemHealth;
  model: OverviewModel;
  runtime: OverviewRuntime;
  trust: OverviewTrust;
  runs: OverviewRuns;
  authorizations: OverviewAuthorizations;
  agent: OverviewAgent | null;
}

// GET /api/v1/health and GET /api/v1/health/llm
export interface HealthResponse {
  status: string;
  service: string;
  phase: string;
  database: string;
}

export interface LLMHealthResponse {
  provider: string;
  configured: boolean;
}

// GET /api/v1/runtime/health
export interface RuntimeHealth {
  available: boolean;
  provider: string;
  detail: string;
  version: string | null;
}

// GET /api/v1/skills and GET /api/v1/tools
export interface SkillView {
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  category: string | null;
  keywords: string[];
  tools: string[];
}

export interface ToolView {
  name: string;
  skill: string;
  description: string;
  risk_level: RiskLevel;
  read_only: boolean;
  side_effect: boolean;
  requires_confirmation: boolean;
  category: string | null;
  version: string;
  input_schema: Record<string, unknown>;
}

// POST /api/v1/agents/{agent_id}/runs and GET /api/v1/agents/runs/{run_id}
export interface AgentActionResponse {
  tool_name: string;
  status: string;
  arguments: Record<string, unknown>;
}

export interface AgentRunResponse {
  run_id: string;
  status: string;
  response?: string | null;
  question?: string | null;
  actions: AgentActionResponse[];
}

// POST /api/v1/llm/generate
export interface LLMTokenUsage {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
}

export interface LLMGenerateResponse {
  content: string;
  model: string;
  usage: LLMTokenUsage | null;
  finish_reason: string | null;
}

// Memories (GET/POST /api/v1/memories)
export interface MemoryDetail {
  id: string;
  agent_id: string;
  content: string;
  memory_type: string;
  source: string;
  importance: string;
  persistence_decision: string;
}

export interface MemoryListResponse {
  items: MemoryDetail[];
}

export interface MemoryDecisionResponse {
  saved: boolean;
  decision: string;
  reason: string;
  memory: MemoryDetail | null;
}

// GET / PATCH /api/v1/settings
export interface SettingsProvider {
  name: string;
  api_key_configured: boolean;
  base_url_configured: boolean;
}

export interface RuntimeSettings {
  model: string;
  temperature: number;
  max_tokens: number;
  request_timeout_seconds: number;
  notifications_enabled: boolean;
  /** Environment values each override falls back to, keyed by field name. */
  defaults: Record<string, unknown>;
  /** Field names that currently carry a saved override. */
  overridden: string[];
  provider: SettingsProvider;
  trust_default_decision: string;
  trust_editable: boolean;
  memory_firewall_enforced: boolean;
  memory_firewall_editable: boolean;
  environment: string;
  updated_at: string | null;
  /** False when the override store could not be read. */
  storage_available: boolean;
}

/**
 * A partial update. Omit a field to leave it alone; send `null` to clear the
 * override and fall back to the environment value.
 */
export interface RuntimeSettingsUpdate {
  model?: string | null;
  temperature?: number | null;
  max_tokens?: number | null;
  request_timeout_seconds?: number | null;
  notifications_enabled?: boolean | null;
}

// GET /api/v1/activity
export type ActivityWindow = 'today' | '24h' | '7d' | 'all';
export type ActivityCategory = 'TOOL' | 'TRUST' | 'MEMORY' | 'RUN' | 'SYSTEM';
export type ActivityOutcome = 'SUCCESS' | 'DENIED' | 'PENDING' | 'ERROR' | 'INFO';

/**
 * One entry in the merged audit feed. The backend joins real, owner-scoped
 * sources (audit decisions, permission requests, runs, actions, memories) --
 * nothing here is synthesised for display.
 */
export interface ActivityEvent {
  id: string;
  timestamp: string;
  category: ActivityCategory | string;
  kind: string;
  outcome: ActivityOutcome | string;
  title: string;
  detail: string;
  source: string | null;
  reference: string | null;
  agent_run_id: string | null;
  risk_level: RiskLevel | string | null;
  decision: string | null;
  payload: Record<string, unknown>;
}

export interface ActivityCategoryCount {
  category: string;
  label: string;
  count: number;
}

export interface ActivitySummary {
  total: number;
  success: number;
  denied: number;
  pending: number;
  error: number;
  info: number;
  resolved: number;
  /** `success / resolved`, or null when nothing in the window reached a verdict. */
  success_rate: number | null;
  categories: ActivityCategoryCount[];
  density: number[];
  density_peak: number;
  bucket_seconds: number;
}

/** The in-memory authorisation ring: bounded, lost on restart, not an archive. */
export interface ActivityAuditTrail {
  persisted: boolean;
  retention_capacity: number;
  retained_entries: number;
  visible_entries: number;
  note: string;
}

export interface ActivityFeed {
  generated_at: string;
  window: string;
  storage_available: boolean;
  truncated: boolean;
  events: ActivityEvent[];
  summary: ActivitySummary;
  audit: ActivityAuditTrail;
}
