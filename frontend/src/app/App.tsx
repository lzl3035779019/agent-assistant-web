import { type FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUp,
  CheckCircle2,
  ChevronDown,
  Database,
  Network,
  PanelRight,
  Search,
  Server,
  LogOut,
} from "lucide-react";

import { api, clearAuthTokens, getAccessToken } from "../api/client";
import type { ConversationSummary, RunCreate } from "../api/types";
import { CalendarPage } from "../components/CalendarPage";
import { AuthPage } from "../components/AuthPage";
import { DailyBriefPage } from "../components/DailyBriefPage";
import { KnowledgePage } from "../components/KnowledgePage";
import { EmailPage } from "../components/EmailPage";
import { MemoryPage } from "../components/MemoryPage";
import { MonitorPage } from "../components/MonitorPage";
import { RunTimeline } from "../components/RunTimeline";
import { TaskCenterPage } from "../components/TaskCenterPage";
import { Sidebar, type WorkspaceView } from "../components/Sidebar";
import { useRunStream } from "../hooks/useRunStream";

interface EvidenceItem {
  citation_id?: string;
  filename?: string;
  page_number?: number | null;
  content?: string;
  score?: number;
}

export default function App() {
  const queryClient = useQueryClient();
  const [sessionVersion, setSessionVersion] = useState(0);
  const authStatus = useQuery({
    queryKey: ["auth-status"],
    queryFn: api.getAuthStatus,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const authRequired = authStatus.data?.enabled ?? false;
  const authenticated = Boolean(getAccessToken());

  if (authStatus.isLoading) return <div className="boot-screen">正在连接 PMAA 服务...</div>;
  if (authStatus.error) return <div className="boot-screen error">无法读取服务配置：{authStatus.error.message}</div>;
  if (authRequired && !authenticated) {
    return <AuthPage key={sessionVersion} onAuthenticated={() => { setSessionVersion((value) => value + 1); void queryClient.invalidateQueries(); }} />;
  }
  return <Workspace authEnabled={authRequired} onLogout={() => { clearAuthTokens(); queryClient.clear(); setSessionVersion((value) => value + 1); }} />;
}

interface WorkspaceProps {
  authEnabled: boolean;
  onLogout: () => void;
}

function Workspace({ authEnabled, onLogout }: WorkspaceProps) {
  const queryClient = useQueryClient();
  const [activeView, setActiveView] = useState<WorkspaceView>("chat");
  const [objective, setObjective] = useState("");
  const [runType, setRunType] = useState<RunCreate["run_type"]>("agentic_rag");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

  const conversationsQuery = useQuery({
    queryKey: ["conversations"],
    queryFn: api.listConversations,
  });
  const conversationQuery = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.getConversation(conversationId!),
    enabled: Boolean(conversationId),
  });

  const createRun = useMutation({
    mutationFn: api.createRun,
    onSuccess(run) {
      setConversationId(run.conversation_id);
      setRunId(run.id);
      setObjective("");
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (run.conversation_id) {
        void queryClient.invalidateQueries({ queryKey: ["conversation", run.conversation_id] });
      }
    },
  });
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      return state === "queued" || state === "running" ? 1500 : false;
    },
  });
  const { events, connected } = useRunStream(runId);
  const running = createRun.isPending || ["queued", "running"].includes(runQuery.data?.status ?? "");
  const evidence = (runQuery.data?.result_payload.evidence ?? []) as EvidenceItem[];
  const messages = conversationQuery.data?.messages ?? [];
  const currentConversation = conversationQuery.data
    ?? conversationsQuery.data?.find((conversation) => conversation.id === conversationId);

  useEffect(() => {
    const status = runQuery.data?.status;
    if (!conversationId || (status !== "completed" && status !== "failed")) return;
    void queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
    void queryClient.invalidateQueries({ queryKey: ["conversations"] });
  }, [conversationId, queryClient, runQuery.data?.status]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = objective.trim();
    if (!value || running) return;
    createRun.mutate({
      objective: value,
      run_type: runType,
      conversation_id: conversationId ?? undefined,
    });
  }

  function selectConversation(conversation: ConversationSummary) {
    setActiveView("chat");
    setConversationId(conversation.id);
    setRunId(conversation.latest_run_id);
    setObjective("");
  }

  function newConversation() {
    setActiveView("chat");
    setConversationId(null);
    setRunId(null);
    setObjective("");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-title"><Network size={18} /><strong>Personal Multi-Agent Assistant</strong><span>Web Platform</span></div>
        <div className="topbar-actions"><div className="system-status"><i />System Online</div>{authEnabled ? <button className="topbar-logout" onClick={async () => { await api.logout(); onLogout(); }} title="退出登录" type="button"><LogOut size={16} /></button> : null}</div>
      </header>

      <div className="workspace-grid">
        <Sidebar
          activeView={activeView}
          conversations={conversationsQuery.data ?? []}
          conversationsLoading={conversationsQuery.isLoading}
          currentConversationId={conversationId}
          onNavigate={setActiveView}
          onConversationDeleted={(deletedConversationId) => {
            if (conversationId === deletedConversationId) newConversation();
          }}
          onNewConversation={newConversation}
          onSelectConversation={selectConversation}
        />
        {activeView === "runs" ? <TaskCenterPage onOpenRun={(run) => { setActiveView("chat"); setConversationId(run.conversation_id); setRunId(run.id); }} /> : activeView === "knowledge" ? <KnowledgePage /> : activeView === "memory" ? <MemoryPage /> : activeView === "email" ? <EmailPage /> : activeView === "calendar" ? <CalendarPage /> : activeView === "brief" ? <DailyBriefPage /> : activeView === "monitor" ? <MonitorPage /> : (
          <>
            <main className="conversation-panel">
              <div className="panel-header">
                <div><span className="eyebrow">SUPERVISOR WORKSPACE</span><h1>{currentConversation?.title ?? "新对话"}</h1></div>
                <div className="header-meta"><Activity size={15} />StateGraph · SSE Trace</div>
              </div>

              <section className="conversation-body">
                {!messages.length && !runQuery.data && !conversationQuery.isLoading ? (
                  <div className="assistant-line">
                    <div className="avatar assistant-avatar">A</div>
                    <div className="message assistant-message">你好，我会根据任务目标决定直接回答、查询知识库或委派专业 Agent。</div>
                  </div>
                ) : null}
                {conversationId && conversationQuery.isLoading ? <div className="conversation-loading">正在加载历史消息...</div> : null}
                {messages
                  .filter((message) => !(message.role === "assistant" && message.run_id === runId))
                  .map((message) => message.role === "user" ? (
                    <div className="user-line" key={message.id}>
                      <div className="message user-message">{message.content}</div>
                      <div className="avatar user-avatar">U</div>
                    </div>
                  ) : (
                    <div className="assistant-line" key={message.id}>
                      <div className="avatar assistant-avatar">A</div>
                      <div className="message assistant-message history-answer">{message.content}</div>
                    </div>
                  ))}
                {runQuery.data ? (
                  <>
                    {!messages.some((message) => message.role === "user" && message.run_id === runQuery.data.id) ? (
                      <div className="user-line">
                        <div className="message user-message">{runQuery.data.objective}</div>
                        <div className="avatar user-avatar">U</div>
                      </div>
                    ) : null}
                    <div className="assistant-line result-line">
                      <div className="avatar assistant-avatar">A</div>
                      <div className="agent-output">
                        <div className="trace-header">
                          <span><Network size={16} />Agent 执行过程</span>
                          <small className={connected ? "connected" : ""}>{connected ? "实时连接" : runQuery.data.status}</small>
                        </div>
                        <RunTimeline events={events} running={running} />
                        {runQuery.data.status === "completed" ? (
                          <div className="answer-block">
                            <div className="answer-title"><CheckCircle2 size={17} />运行结果</div>
                            <div className="answer-copy">{String(runQuery.data.result_payload.answer ?? "任务已完成。")}</div>
                          </div>
                        ) : null}
                        {runQuery.data.status === "failed" ? <div className="error-block">{runQuery.data.error}</div> : null}
                      </div>
                    </div>
                  </>
                ) : null}
              </section>

              <form className="composer" onSubmit={submit}>
                <div className="mode-switch" aria-label="执行模式">
                  <button className={runType === "assistant" ? "selected" : ""} onClick={() => setRunType("assistant")} type="button">智能助手</button>
                  <button className={runType === "agentic_rag" ? "selected" : ""} onClick={() => setRunType("agentic_rag")} type="button">Agentic RAG</button>
                  <button className={runType === "research" ? "selected" : ""} onClick={() => setRunType("research")} type="button">联网研究</button>
                </div>
                <div className="composer-row">
                  <textarea
                    aria-label="任务输入"
                    onChange={(event) => setObjective(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        event.currentTarget.form?.requestSubmit();
                      }
                    }}
                    placeholder="输入需要完成的任务，按 Enter 发送"
                    rows={2}
                    value={objective}
                  />
                  <button className="send-button" disabled={!objective.trim() || running} title="发送任务" type="submit"><ArrowUp size={20} /></button>
                </div>
                {createRun.error ? <div className="composer-error">{createRun.error.message}</div> : null}
              </form>
            </main>

            <aside className="context-panel">
              <div className="context-title"><PanelRight size={17} /><strong>运行上下文</strong></div>
              <div className="context-body">
                <div className="context-section">
                  <span className="section-caption">RUNTIME</span>
                  <div className="runtime-grid">
                    <div><Server size={17} /><span>FastAPI</span><strong>Ready</strong></div>
                    <div><Database size={17} /><span>PostgreSQL</span><strong>Source of truth</strong></div>
                    <div><Activity size={17} /><span>Event stream</span><strong>{connected ? "Connected" : "Idle"}</strong></div>
                    <div><Search size={17} /><span>Knowledge</span><strong>Agentic RAG</strong></div>
                  </div>
                </div>
                <div className="context-section">
                  <span className="section-caption">CURRENT RUN</span>
                  {runQuery.data ? (
                    <dl className="run-facts">
                      <div><dt>Run ID</dt><dd>{runQuery.data.id.slice(0, 12)}</dd></div>
                      <div><dt>类型</dt><dd>{runQuery.data.run_type}</dd></div>
                      <div><dt>状态</dt><dd className={`status-${runQuery.data.status}`}>{runQuery.data.status}</dd></div>
                      <div><dt>事件</dt><dd>{events.length}</dd></div>
                    </dl>
                  ) : <p className="context-empty">尚未创建任务。</p>}
                </div>
                {evidence.length ? (
                  <div className="context-section">
                    <span className="section-caption">EVIDENCE</span>
                    <div className="evidence-list">
                      {evidence.map((item, index) => {
                        const evidenceId = `${item.citation_id ?? `S${index + 1}`}-${index}`;
                        const expanded = expandedEvidence === evidenceId;
                        return (
                          <article className={`evidence-card${expanded ? " expanded" : ""}`} key={evidenceId}>
                            <button
                              aria-expanded={expanded}
                              className="evidence-summary"
                              onClick={() => setExpandedEvidence(expanded ? null : evidenceId)}
                              type="button"
                            >
                              <span className="evidence-heading">
                                <strong>[{item.citation_id ?? `S${index + 1}`}] {item.filename ?? "知识文档"}</strong>
                                <ChevronDown size={14} />
                              </span>
                              <span className="evidence-meta">
                                {item.page_number ? `第 ${item.page_number} 页 · ` : ""}相关度 {Math.round((item.score ?? 0) * 100)}%
                              </span>
                            </button>
                            <div className="evidence-preview">
                              <span className="evidence-preview-label">证据原文</span>
                              <p>{item.content?.trim() || "当前检索结果没有返回可展示的证据文本。"}</p>
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            </aside>
          </>
        )}
      </div>
    </div>
  );
}
