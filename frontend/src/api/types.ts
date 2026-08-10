export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentRun {
  id: string;
  user_id: string;
  conversation_id: string | null;
  objective: string;
  run_type: string;
  status: RunStatus;
  idempotency_key: string;
  retry_of_run_id: string | null;
  cancel_requested_at: string | null;
  attempt_count: number;
  max_attempts: number;
  next_retry_at: string | null;
  result_payload: Record<string, unknown>;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunPage {
  items: AgentRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuthStatus {
  enabled: boolean;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  active: boolean;
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthUser;
}

export interface AuthCredentials {
  email: string;
  password: string;
  display_name?: string;
}

export interface RunEvent {
  id: string;
  run_id: string;
  sequence: number;
  event_type: string;
  agent_id: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RunCreate {
  objective: string;
  run_type: "assistant" | "agentic_rag" | "research" | "email" | "calendar" | "daily_brief" | "monitor";
  conversation_id?: string;
  input_payload?: Record<string, unknown>;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  run_id: string | null;
  sequence: number;
  role: "user" | "assistant" | "system";
  content: string;
  message_metadata: Record<string, unknown>;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  message_count: number;
  last_message: string;
  latest_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation extends ConversationSummary {
  messages: ConversationMessage[];
}

export interface KnowledgeDocument {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: "queued" | "processing" | "indexed" | "failed";
  error: string;
  chunk_count: number;
  document_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
}

export interface KnowledgeStats {
  document_count: number;
  indexed_count: number;
  processing_count: number;
  failed_count: number;
  chunk_count: number;
}

export type MemoryType = "profile" | "preference" | "project" | "instruction";

export interface UserMemory {
  id: string;
  user_id: string;
  memory_type: MemoryType;
  content: string;
  source_conversation_id: string | null;
  source_message_id: string | null;
  source: string;
  confidence: number;
  validation_reason: string;
  enabled: boolean;
  usage_count: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryStats {
  total: number;
  enabled: number;
  disabled: number;
  by_type: Record<string, number>;
}

export interface MemoryCreate {
  memory_type: MemoryType;
  content: string;
  confidence?: number;
}

export interface MemoryUpdate {
  memory_type?: MemoryType;
  content?: string;
  confidence?: number;
  enabled?: boolean;
}

export interface EmailStatus {
  enabled: boolean;
  configured: boolean;
  address: string;
  provider: "qq";
}

export interface EmailMessage {
  uid: string;
  from_address: string;
  subject: string;
  sent_at: string;
  snippet: string;
  unread: boolean;
  body: string;
}

export interface EmailUnreadCount {
  count: number;
  scope: "today" | "all";
}

export interface EmailDraft {
  to: string;
  subject: string;
  body: string;
  source_message_uid: string;
}

export interface EmailSendAction {
  id: string;
  recipient: string;
  subject: string;
  body: string;
  source_message_uid: string;
  status: "pending" | "sending" | "sent" | "failed" | "cancelled";
  provider_message_id: string;
  error: string;
  created_at: string;
  confirmed_at: string | null;
  sent_at: string | null;
}

export interface EmailSendActionCreate {
  to: string;
  subject: string;
  body: string;
  source_message_uid?: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  description: string;
  location: string;
  start_at: string;
  end_at: string;
  status: "active" | "cancelled";
  provider: string;
  provider_event_id: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface TodoItem {
  id: string;
  title: string;
  description: string;
  status: "todo" | "in_progress" | "completed" | "cancelled";
  due_at: string | null;
  priority: number;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface CalendarStats {
  today_events: number;
  upcoming_events: number;
  open_todos: number;
  overdue_todos: number;
}

export type CalendarActionType =
  | "event.create"
  | "event.update"
  | "event.cancel"
  | "todo.create"
  | "todo.update"
  | "todo.cancel";

export interface CalendarAction {
  id: string;
  action: CalendarActionType;
  target_id: string | null;
  payload: Record<string, unknown>;
  status: "pending" | "executing" | "executed" | "failed" | "cancelled";
  result_payload: {
    has_conflict?: boolean;
    conflicts?: Array<{ id: string; title: string; start_at: string; end_at: string }>;
    target_type?: string;
    target_id?: string;
  };
  error: string;
  created_at: string;
  confirmed_at: string | null;
  executed_at: string | null;
}

export interface CalendarActionCreate {
  action: CalendarActionType;
  target_id?: string;
  payload: Record<string, unknown>;
}

export interface BriefSchedule {
  id: string;
  name: string;
  local_time: string;
  timezone: string;
  weekdays: number[];
  topics: string[];
  include_email: boolean;
  include_calendar: boolean;
  include_memory: boolean;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BriefScheduleCreate {
  name: string;
  local_time: string;
  timezone: string;
  weekdays: number[];
  topics: string[];
  include_email: boolean;
  include_calendar: boolean;
  include_memory: boolean;
  enabled: boolean;
}

export type BriefScheduleUpdate = Partial<BriefScheduleCreate>;

export interface BriefSections {
  summary?: string;
  topics?: string[];
  priorities?: string[];
  email?: Array<{ uid: string; from: string; subject: string; sent_at: string; snippet: string }>;
  calendar?: Array<{
    kind: "event" | "todo";
    title: string;
    start_at?: string;
    end_at?: string;
    due_at?: string | null;
    location?: string;
    priority?: number;
    overdue?: boolean;
  }>;
  news?: Array<{ topic: string; title: string; url: string; snippet: string; score: number }>;
  memory?: Array<{ type: string; content: string; confidence: number }>;
  warnings?: string[];
}

export interface DailyBrief {
  id: string;
  schedule_id: string | null;
  title: string;
  status: "queued" | "running" | "completed" | "failed";
  topics: string[];
  include_email: boolean;
  include_calendar: boolean;
  include_memory: boolean;
  sections: BriefSections;
  content: string;
  error: string;
  unread: boolean;
  source: "manual" | "scheduled";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  read_at: string | null;
}

export interface DailyBriefStats {
  unread_count: number;
  total_count: number;
  active_schedule_count: number;
  generating_count: number;
}

export interface DailyBriefGenerate {
  schedule_id?: string;
  topics: string[];
  include_email: boolean;
  include_calendar: boolean;
  include_memory: boolean;
}

export type MonitorTargetType = "news" | "github" | "company" | "blog";

export interface MonitorRule {
  id: string;
  name: string;
  target_type: MonitorTargetType;
  query: string;
  interval_minutes: number;
  enabled: boolean;
  last_result: Array<{
    title?: string;
    url?: string;
    summary?: string;
    published_at?: string | null;
    score?: number;
    source?: string;
  }>;
  last_run_status: string;
  last_error: string;
  last_run_id: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MonitorRuleCreate {
  name: string;
  target_type: MonitorTargetType;
  query: string;
  interval_minutes: number;
  enabled: boolean;
}

export type MonitorRuleUpdate = Partial<MonitorRuleCreate>;

export interface MonitorNotification {
  id: string;
  rule_id: string;
  title: string;
  summary: string;
  payload: {
    items?: MonitorRule["last_result"];
    run_id?: string;
  };
  unread: boolean;
  created_at: string;
  read_at: string | null;
}

export interface MonitorResult {
  id: string;
  rule_id: string;
  run_id: string | null;
  rule_name: string;
  target_type: MonitorTargetType;
  summary: string;
  item_count: number;
  change_count: number;
  baseline_created: boolean;
  payload: {
    items?: MonitorRule["last_result"];
    new_items?: MonitorRule["last_result"];
  };
  created_at: string;
}

export interface MonitorResultPage {
  items: MonitorResult[];
  total: number;
  limit: number;
  offset: number;
}

export interface MonitorStats {
  rule_count: number;
  enabled_count: number;
  unread_count: number;
  running_count: number;
}
