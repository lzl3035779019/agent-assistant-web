import {
  Bell,
  BookOpen,
  Bot,
  CalendarDays,
  FileSearch,
  Inbox,
  Check,
  MemoryStick,
  MessageSquare,
  ListChecks,
  MoreHorizontal,
  Pencil,
  Plus,
  Radar,
  Trash2,
  X,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { ConversationSummary } from "../api/types";

export type WorkspaceView = "chat" | "runs" | "knowledge" | "memory" | "email" | "calendar" | "brief" | "monitor";

const sections = [
  { id: "chat", label: "对话", caption: "Chat", icon: MessageSquare },
  { id: "runs", label: "任务中心", caption: "Runs", icon: ListChecks },
  { id: "knowledge", label: "知识库", caption: "Agentic RAG", icon: BookOpen },
  { id: "memory", label: "记忆系统", caption: "Memory", icon: MemoryStick },
  { id: "email", label: "邮件助手", caption: "Email", icon: Inbox },
  { id: "calendar", label: "日历与任务", caption: "Calendar", icon: CalendarDays },
  { id: "brief", label: "每日简报", caption: "Daily Brief", icon: Bell },
  { id: "monitor", label: "信息监控", caption: "Monitor", icon: Radar },
] as const;

interface Props {
  activeView: WorkspaceView;
  conversations: ConversationSummary[];
  currentConversationId: string | null;
  conversationsLoading: boolean;
  onNavigate: (view: WorkspaceView) => void;
  onNewConversation: () => void;
  onSelectConversation: (conversation: ConversationSummary) => void;
  onConversationDeleted: (conversationId: string) => void;
}

export function Sidebar({
  activeView,
  conversations,
  currentConversationId,
  conversationsLoading,
  onNavigate,
  onNewConversation,
  onSelectConversation,
  onConversationDeleted,
}: Props) {
  const queryClient = useQueryClient();
  const sidebarRef = useRef<HTMLElement>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [actionError, setActionError] = useState("");
  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.renameConversation(id, title),
    async onSuccess(conversation) {
      setEditingId(null);
      setOpenMenuId(null);
      setActionError("");
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      await queryClient.invalidateQueries({ queryKey: ["conversation", conversation.id] });
    },
    onError(error) {
      setActionError(error instanceof Error ? error.message : "重命名失败");
    },
  });
  const deleteMutation = useMutation({
    mutationFn: api.deleteConversation,
    async onSuccess(_, conversationId) {
      setOpenMenuId(null);
      setActionError("");
      onConversationDeleted(conversationId);
      queryClient.removeQueries({ queryKey: ["conversation", conversationId] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError(error) {
      setActionError(error instanceof Error ? error.message : "删除失败");
    },
  });

  useEffect(() => {
    if (!openMenuId) return;
    const closeMenu = (event: PointerEvent) => {
      const target = event.target as Element;
      if (!target.closest(".recent-more") && !target.closest(".recent-row-menu")) {
        setOpenMenuId(null);
      }
    };
    document.addEventListener("pointerdown", closeMenu);
    return () => document.removeEventListener("pointerdown", closeMenu);
  }, [openMenuId]);

  function beginRename(conversation: ConversationSummary) {
    setEditingId(conversation.id);
    setTitleDraft(conversation.title);
    setOpenMenuId(null);
    setActionError("");
  }

  function submitRename(event: FormEvent, conversation: ConversationSummary) {
    event.preventDefault();
    const title = titleDraft.trim();
    if (!title) {
      setActionError("对话名称不能为空");
      return;
    }
    if (title === conversation.title) {
      setEditingId(null);
      return;
    }
    renameMutation.mutate({ id: conversation.id, title });
  }

  function requestDelete(conversation: ConversationSummary) {
    setOpenMenuId(null);
    if (!window.confirm(`确定删除对话“${conversation.title}”吗？删除后无法恢复。`)) return;
    deleteMutation.mutate(conversation.id);
  }

  const unreadQuery = useQuery({
    queryKey: ["email-unread-count"],
    queryFn: () => api.getEmailUnreadCount(true),
    refetchInterval: 60_000,
    retry: false,
  });
  const calendarStatsQuery = useQuery({
    queryKey: ["calendar-stats"],
    queryFn: api.getCalendarStats,
    refetchInterval: 60_000,
    retry: false,
  });
  const briefStatsQuery = useQuery({
    queryKey: ["daily-brief-stats"],
    queryFn: api.getDailyBriefStats,
    refetchInterval: 60_000,
    retry: false,
  });
  const monitorStatsQuery = useQuery({
    queryKey: ["monitor-stats"],
    queryFn: api.getMonitorStats,
    refetchInterval: 60_000,
    retry: false,
  });
  return (
    <aside className="sidebar" ref={sidebarRef}>
      <div className="brand-block">
        <div className="brand-mark"><Bot size={19} /></div>
        <div><strong>PMAA</strong><span>Multi-Agent Workspace</span></div>
      </div>

      <nav className="primary-nav" aria-label="主要功能">
        {sections.map((section) => {
          const { id, label, caption, icon: Icon } = section;
          const badge = id === "email"
            ? unreadQuery.data?.count
            : id === "calendar"
              ? calendarStatsQuery.data?.today_events
              : id === "brief"
                ? briefStatsQuery.data?.unread_count
                : id === "monitor"
                  ? monitorStatsQuery.data?.unread_count
              : undefined;
          const available = true;
          return (
            <button
              className={`nav-item${activeView === id ? " active" : ""}`}
              disabled={!available}
              key={id}
              onClick={() => available && onNavigate(id)}
              title={available ? label : `${label}将在后续里程碑接入`}
              type="button"
            >
              <Icon size={18} />
              <span className="nav-copy"><strong>{label}</strong><small>{caption}</small></span>
              {badge ? <span className="nav-badge">{badge}</span> : null}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-divider" />
      <button className="new-chat" onClick={onNewConversation} type="button">
        <Plus size={17} />新建对话
      </button>
      <div className="recent-label">最近对话</div>
      <div className="recent-list">
        {conversationsLoading ? <span className="recent-empty">正在加载...</span> : null}
        {!conversationsLoading && !conversations.length ? <span className="recent-empty">暂无历史对话</span> : null}
        {conversations.map((conversation) => (
          <div
            className={`recent-row${currentConversationId === conversation.id ? " active" : ""}`}
            key={conversation.id}
          >
            {editingId === conversation.id ? (
              <form className="recent-rename" onSubmit={(event) => submitRename(event, conversation)}>
                <input
                  aria-label="对话名称"
                  autoFocus
                  maxLength={512}
                  onChange={(event) => setTitleDraft(event.target.value)}
                  value={titleDraft}
                />
                <button aria-label="保存名称" disabled={renameMutation.isPending} title="保存" type="submit">
                  <Check size={14} />
                </button>
                <button aria-label="取消重命名" onClick={() => setEditingId(null)} title="取消" type="button">
                  <X size={14} />
                </button>
              </form>
            ) : (
              <>
                <button
                  className="recent-select"
                  onClick={() => onSelectConversation(conversation)}
                  title={conversation.title}
                  type="button"
                >
                  <FileSearch size={15} />
                  <span>{conversation.title}</span>
                </button>
                <button
                  aria-expanded={openMenuId === conversation.id}
                  aria-haspopup="menu"
                  aria-label={`管理对话：${conversation.title}`}
                  className="recent-more"
                  onClick={(event) => {
                    event.stopPropagation();
                    setActionError("");
                    setOpenMenuId((current) => current === conversation.id ? null : conversation.id);
                  }}
                  title="更多"
                  type="button"
                >
                  <MoreHorizontal size={16} />
                </button>
                {openMenuId === conversation.id ? (
                  <div className="recent-row-menu" role="menu">
                    <button onClick={() => beginRename(conversation)} role="menuitem" type="button">
                      <Pencil size={15} />重命名
                    </button>
                    <button className="danger" onClick={() => requestDelete(conversation)} role="menuitem" type="button">
                      <Trash2 size={15} />删除
                    </button>
                  </div>
                ) : null}
              </>
            )}
          </div>
        ))}
        {actionError ? <span className="recent-action-error">{actionError}</span> : null}
      </div>
    </aside>
  );
}
