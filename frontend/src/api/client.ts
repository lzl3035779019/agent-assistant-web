import type {
  AgentRun,
  AuthCredentials,
  AuthStatus,
  AuthTokens,
  AuthUser,
  CalendarAction,
  CalendarActionCreate,
  CalendarEvent,
  CalendarStats,
  BriefSchedule,
  BriefScheduleCreate,
  BriefScheduleUpdate,
  Conversation,
  ConversationSummary,
  DailyBrief,
  DailyBriefGenerate,
  DailyBriefStats,
  EmailDraft,
  EmailMessage,
  EmailSendAction,
  EmailSendActionCreate,
  EmailStatus,
  EmailUnreadCount,
  KnowledgeDocument,
  KnowledgeStats,
  MemoryCreate,
  MemoryStats,
  MemoryUpdate,
  MonitorNotification,
  MonitorResultPage,
  MonitorRule,
  MonitorRuleCreate,
  MonitorRuleUpdate,
  MonitorStats,
  RunCreate,
  RunPage,
  RunStatus,
  TodoItem,
  UserMemory,
} from "./types";

const API_PREFIX = "/api/v1";
const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const USES_NGROK_FREE = /\.ngrok-free\.(app|dev)(?:\/|$)/i.test(API_ORIGIN);
const ACCESS_TOKEN_KEY = "pmaa.access_token";
const REFRESH_TOKEN_KEY = "pmaa.refresh_token";

export function buildApiUrl(path: string) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_ORIGIN}${API_PREFIX}${normalizedPath}`;
}

export function getAccessToken() {
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function saveAuthTokens(tokens: AuthTokens) {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
  window.dispatchEvent(new Event("pmaa-auth-changed"));
}

export function clearAuthTokens() {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.dispatchEvent(new Event("pmaa-auth-changed"));
}

let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken() {
  const refreshToken = window.localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return false;
  if (!refreshPromise) {
    refreshPromise = fetch(buildApiUrl("/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (response) => {
        if (!response.ok) return false;
        saveAuthTokens(await response.json() as AuthTokens);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function request<T>(path: string, init?: RequestInit, allowRefresh = true): Promise<T> {
  const headers = new Headers(init?.headers);
  if (USES_NGROK_FREE) headers.set("ngrok-skip-browser-warning", "1");
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const accessToken = getAccessToken();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(buildApiUrl(path), { ...init, headers });
  if (response.status === 401 && allowRefresh && await refreshAccessToken()) {
    return request<T>(path, init, false);
  }
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try {
      message = JSON.parse(body).detail ?? body;
    } catch {
      // Keep the original response body.
    }
    if (response.status === 401) clearAuthTokens();
    throw new Error(message || `请求失败：${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  getAuthStatus() {
    return request<AuthStatus>("/auth/status", undefined, false);
  },
  register(payload: AuthCredentials) {
    return request<AuthTokens>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }, false);
  },
  login(payload: AuthCredentials) {
    return request<AuthTokens>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }, false);
  },
  getCurrentUser() {
    return request<AuthUser>("/auth/me");
  },
  async logout() {
    const refreshToken = window.localStorage.getItem(REFRESH_TOKEN_KEY);
    try {
      if (refreshToken) {
        await request<void>("/auth/logout", {
          method: "POST",
          body: JSON.stringify({ refresh_token: refreshToken }),
        }, false);
      }
    } finally {
      clearAuthTokens();
    }
  },
  createRun(payload: RunCreate) {
    return request<AgentRun>("/runs", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(payload),
    });
  },
  listRuns(params?: { status?: RunStatus; limit?: number; offset?: number }) {
    const search = new URLSearchParams({
      limit: String(params?.limit ?? 12),
      offset: String(params?.offset ?? 0),
    });
    if (params?.status) search.set("status", params.status);
    return request<RunPage>(`/runs?${search.toString()}`);
  },
  getRun(runId: string) {
    return request<AgentRun>(`/runs/${runId}`);
  },
  cancelRun(runId: string) {
    return request<AgentRun>(`/runs/${runId}/cancel`, { method: "POST" });
  },
  retryRun(runId: string) {
    return request<AgentRun>(`/runs/${runId}/retry`, { method: "POST" });
  },
  listConversations() {
    return request<ConversationSummary[]>("/conversations?limit=80");
  },
  getConversation(conversationId: string) {
    return request<Conversation>(`/conversations/${conversationId}`);
  },
  renameConversation(conversationId: string, title: string) {
    return request<ConversationSummary>(`/conversations/${conversationId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  },
  deleteConversation(conversationId: string) {
    return request<void>(`/conversations/${conversationId}`, { method: "DELETE" });
  },
  listDocuments() {
    return request<KnowledgeDocument[]>("/knowledge/documents");
  },
  getKnowledgeStats() {
    return request<KnowledgeStats>("/knowledge/stats");
  },
  uploadDocument(file: File) {
    const form = new FormData();
    form.append("file", file);
    return request<KnowledgeDocument>("/knowledge/documents", {
      method: "POST",
      body: form,
    });
  },
  deleteDocument(documentId: string) {
    return request<void>(`/knowledge/documents/${documentId}`, {
      method: "DELETE",
    });
  },
  listMemories(params?: { memoryType?: string; enabled?: boolean; query?: string }) {
    const search = new URLSearchParams();
    if (params?.memoryType) search.set("memory_type", params.memoryType);
    if (params?.enabled !== undefined) search.set("enabled", String(params.enabled));
    if (params?.query) search.set("query", params.query);
    const suffix = search.size ? `?${search.toString()}` : "";
    return request<UserMemory[]>(`/memories${suffix}`);
  },
  getMemoryStats() {
    return request<MemoryStats>("/memories/stats");
  },
  createMemory(payload: MemoryCreate) {
    return request<UserMemory>("/memories", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateMemory(memoryId: string, payload: MemoryUpdate) {
    return request<UserMemory>(`/memories/${memoryId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  deleteMemory(memoryId: string) {
    return request<void>(`/memories/${memoryId}`, { method: "DELETE" });
  },
  getEmailStatus() {
    return request<EmailStatus>("/email/status");
  },
  getEmailUnreadCount(todayOnly = true) {
    return request<EmailUnreadCount>(`/email/unread-count?today_only=${todayOnly}`);
  },
  listEmailMessages(params?: {
    limit?: number;
    unreadOnly?: boolean;
    startDate?: string;
    endDate?: string;
  }) {
    const search = new URLSearchParams({
      limit: String(params?.limit ?? 10),
      unread_only: String(params?.unreadOnly ?? false),
    });
    if (params?.startDate) search.set("start_date", params.startDate);
    if (params?.endDate) search.set("end_date", params.endDate);
    return request<EmailMessage[]>(`/email/messages?${search.toString()}`);
  },
  getEmailMessage(uid: string) {
    return request<EmailMessage>(`/email/messages/${encodeURIComponent(uid)}`);
  },
  markEmailRead(uid: string) {
    return request<EmailMessage>(`/email/messages/${encodeURIComponent(uid)}/read`, {
      method: "POST",
    });
  },
  createEmailReplyDraft(messageUid: string) {
    return request<EmailDraft>("/email/drafts/reply", {
      method: "POST",
      body: JSON.stringify({ message_uid: messageUid }),
    });
  },
  listEmailSendActions() {
    return request<EmailSendAction[]>("/email/send-actions");
  },
  prepareEmailSend(payload: EmailSendActionCreate) {
    return request<EmailSendAction>("/email/send-actions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  confirmEmailSend(actionId: string) {
    return request<EmailSendAction>(`/email/send-actions/${actionId}/confirm`, {
      method: "POST",
    });
  },
  cancelEmailSend(actionId: string) {
    return request<EmailSendAction>(`/email/send-actions/${actionId}/cancel`, {
      method: "POST",
    });
  },
  getCalendarStats() {
    return request<CalendarStats>("/calendar/stats");
  },
  listCalendarEvents(params: { startAt: string; endAt: string }) {
    const search = new URLSearchParams({ start_at: params.startAt, end_at: params.endAt });
    return request<CalendarEvent[]>(`/calendar/events?${search.toString()}`);
  },
  listTodos(includeCompleted = false) {
    return request<TodoItem[]>(`/calendar/todos?include_completed=${includeCompleted}`);
  },
  prepareCalendarAction(payload: CalendarActionCreate) {
    return request<CalendarAction>("/calendar/actions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  confirmCalendarAction(actionId: string) {
    return request<CalendarAction>(`/calendar/actions/${actionId}/confirm`, {
      method: "POST",
    });
  },
  cancelCalendarAction(actionId: string) {
    return request<CalendarAction>(`/calendar/actions/${actionId}/cancel`, {
      method: "POST",
    });
  },
  getDailyBriefStats() {
    return request<DailyBriefStats>("/daily-briefs/stats");
  },
  listBriefSchedules() {
    return request<BriefSchedule[]>("/daily-briefs/schedules");
  },
  createBriefSchedule(payload: BriefScheduleCreate) {
    return request<BriefSchedule>("/daily-briefs/schedules", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateBriefSchedule(scheduleId: string, payload: BriefScheduleUpdate) {
    return request<BriefSchedule>(`/daily-briefs/schedules/${scheduleId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  deleteBriefSchedule(scheduleId: string) {
    return request<void>(`/daily-briefs/schedules/${scheduleId}`, { method: "DELETE" });
  },
  generateDailyBrief(payload: DailyBriefGenerate) {
    return request<DailyBrief>("/daily-briefs/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  listDailyBriefs(unreadOnly = false) {
    return request<DailyBrief[]>(`/daily-briefs?unread_only=${unreadOnly}`);
  },
  getDailyBrief(briefId: string) {
    return request<DailyBrief>(`/daily-briefs/${briefId}`);
  },
  markDailyBriefRead(briefId: string) {
    return request<DailyBrief>(`/daily-briefs/${briefId}/read`, { method: "POST" });
  },
  markAllDailyBriefsRead() {
    return request<void>("/daily-briefs/read-all", { method: "POST" });
  },
  getMonitorStats() {
    return request<MonitorStats>("/monitors/stats");
  },
  listMonitorRules() {
    return request<MonitorRule[]>("/monitors/rules");
  },
  createMonitorRule(payload: MonitorRuleCreate) {
    return request<MonitorRule>("/monitors/rules", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateMonitorRule(ruleId: string, payload: MonitorRuleUpdate) {
    return request<MonitorRule>(`/monitors/rules/${ruleId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  deleteMonitorRule(ruleId: string) {
    return request<void>(`/monitors/rules/${ruleId}`, { method: "DELETE" });
  },
  runMonitorRule(ruleId: string) {
    return request<AgentRun>(`/monitors/rules/${ruleId}/run`, { method: "POST" });
  },
  listMonitorResults(ruleId?: string, limit = 9, offset = 0) {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (ruleId) params.set("rule_id", ruleId);
    return request<MonitorResultPage>(`/monitors/results?${params.toString()}`);
  },
  deleteMonitorResult(resultId: string) {
    return request<void>(`/monitors/results/${resultId}`, { method: "DELETE" });
  },
  clearMonitorResults(ruleId?: string) {
    const query = ruleId ? `?rule_id=${encodeURIComponent(ruleId)}` : "";
    return request<void>(`/monitors/results${query}`, { method: "DELETE" });
  },
  listMonitorNotifications(unreadOnly = false) {
    return request<MonitorNotification[]>(`/monitors/notifications?unread_only=${unreadOnly}`);
  },
  markMonitorNotificationRead(notificationId: string) {
    return request<MonitorNotification>(`/monitors/notifications/${notificationId}/read`, {
      method: "POST",
    });
  },
  markAllMonitorNotificationsRead() {
    return request<void>("/monitors/notifications/read-all", { method: "POST" });
  },
};
