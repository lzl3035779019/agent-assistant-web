import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Clock3,
  Eye,
  Inbox,
  Mail,
  RefreshCw,
  Reply,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";

import { api } from "../api/client";
import type { EmailDraft, EmailMessage } from "../api/types";

function formatSender(value: string) {
  return value.replace(/<([^>]+)>/, "<$1>");
}

function statusCopy(status: string) {
  return {
    pending: "等待确认",
    sending: "正在发送",
    sent: "已发送",
    failed: "发送失败",
    cancelled: "已取消",
  }[status] ?? status;
}

const emptyDraft: EmailDraft = {
  to: "",
  subject: "",
  body: "",
  source_message_uid: "",
};

type EmailTimeRange = "all" | "today" | "7d" | "30d" | "custom";

function localDateValue(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function presetDateRange(range: EmailTimeRange) {
  if (range === "all" || range === "custom") return { startDate: "", endDate: "" };
  const end = new Date();
  const start = new Date(end);
  if (range === "7d") start.setDate(start.getDate() - 6);
  if (range === "30d") start.setDate(start.getDate() - 29);
  return { startDate: localDateValue(start), endDate: localDateValue(end) };
}

export function EmailPage() {
  const queryClient = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [limit, setLimit] = useState(10);
  const [limitInput, setLimitInput] = useState("10");
  const [timeRange, setTimeRange] = useState<EmailTimeRange>("all");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [selectedMessage, setSelectedMessage] = useState<EmailMessage | null>(null);
  const [draft, setDraft] = useState<EmailDraft>(emptyDraft);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["email-status"],
    queryFn: api.getEmailStatus,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    retry: 3,
    retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 5_000),
  });
  const presetRange = presetDateRange(timeRange);
  const startDate = timeRange === "custom" ? customStartDate : presetRange.startDate;
  const endDate = timeRange === "custom" ? customEndDate : presetRange.endDate;
  const messagesQuery = useQuery({
    queryKey: ["email-messages", { unreadOnly, limit, startDate, endDate }],
    queryFn: () => api.listEmailMessages({ limit, unreadOnly, startDate, endDate }),
    enabled: statusQuery.data?.configured === true,
    staleTime: 30_000,
  });
  const actionsQuery = useQuery({
    queryKey: ["email-send-actions"],
    queryFn: api.listEmailSendActions,
  });

  const openMessage = useMutation({
    mutationFn: api.markEmailRead,
    onSuccess(message) {
      setSelectedMessage(message);
      queryClient.setQueriesData<EmailMessage[]>({ queryKey: ["email-messages"] }, (current) =>
        current?.map((item) => item.uid === message.uid ? { ...item, unread: false } : item),
      );
      void queryClient.invalidateQueries({ queryKey: ["email-unread-count"] });
    },
  });

  const createReply = useMutation({
    mutationFn: api.createEmailReplyDraft,
    onSuccess(value) {
      setDraft(value);
      setPendingActionId(null);
    },
  });
  const prepareSend = useMutation({
    mutationFn: api.prepareEmailSend,
    onSuccess(action) {
      setPendingActionId(action.id);
      void queryClient.invalidateQueries({ queryKey: ["email-send-actions"] });
    },
  });
  const confirmSend = useMutation({
    mutationFn: api.confirmEmailSend,
    onSuccess() {
      setPendingActionId(null);
      setDraft(emptyDraft);
      void queryClient.invalidateQueries({ queryKey: ["email-send-actions"] });
    },
  });
  const cancelSend = useMutation({
    mutationFn: api.cancelEmailSend,
    onSuccess() {
      setPendingActionId(null);
      void queryClient.invalidateQueries({ queryKey: ["email-send-actions"] });
    },
  });

  const pendingAction = actionsQuery.data?.find((item) => item.id === pendingActionId);

  useEffect(() => {
    if (!pendingActionId) return;
    const action = actionsQuery.data?.find((item) => item.id === pendingActionId);
    if (action && action.status !== "pending") setPendingActionId(null);
  }, [actionsQuery.data, pendingActionId]);

  async function refreshInbox() {
    setSelectedMessage(null);
    const status = await statusQuery.refetch();
    if (status.data?.configured) await messagesQuery.refetch();
    await queryClient.invalidateQueries({ queryKey: ["email-unread-count"] });
  }

  function updateDraft(field: keyof EmailDraft, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
    setPendingActionId(null);
  }

  function applyLimit() {
    const parsed = Number.parseInt(limitInput, 10);
    const next = Number.isFinite(parsed) ? Math.min(100, Math.max(1, parsed)) : 10;
    setLimit(next);
    setLimitInput(String(next));
  }

  return (
    <main className="email-workspace">
      <header className="module-header">
        <div>
          <span className="eyebrow">EMAIL AGENT</span>
          <h1>邮件助手</h1>
          <p>读取与分析 QQ 邮件、选择邮件生成回复草稿，并通过用户确认后执行发送。</p>
        </div>
        <div className={`email-connection ${statusQuery.data?.configured ? "ready" : ""}`}>
          <span>{statusQuery.data?.configured ? "已连接" : "未配置"}</span>
          <strong>{statusQuery.data?.address || "QQ Mail"}</strong>
        </div>
      </header>

      {statusQuery.error ? (
        <div className="module-warning">邮件服务暂时无法访问，页面会自动重试；也可以点击收件箱右上角刷新。</div>
      ) : null}
      {!statusQuery.isLoading && !statusQuery.error && statusQuery.data && !statusQuery.data.configured ? (
        <div className="module-warning">邮件模块未启用或 QQ 邮箱配置不完整，请检查服务端环境变量。</div>
      ) : null}

      <div className="email-content">
        <section className="email-inbox-panel">
          <div className="email-section-title">
            <div><Inbox size={18} /><strong>收件箱</strong></div>
            <button onClick={refreshInbox} title="刷新收件箱" type="button"><RefreshCw size={15} /></button>
          </div>
          <div className="email-toolbar">
            <label className="email-switch">
              <input checked={unreadOnly} onChange={(event) => setUnreadOnly(event.target.checked)} type="checkbox" />
              <span />只看未读
            </label>
            <div className="email-filter-controls">
              <label>时间范围
              <select onChange={(event) => setTimeRange(event.target.value as EmailTimeRange)} value={timeRange}>
                <option value="all">全部时间</option>
                <option value="today">今天</option>
                <option value="7d">近 7 天</option>
                <option value="30d">近 30 天</option>
                <option value="custom">自定义</option>
              </select>
              </label>
              <label>读取数量
                <input
                  inputMode="numeric"
                  max={100}
                  min={1}
                  onBlur={applyLimit}
                  onChange={(event) => setLimitInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") event.currentTarget.blur();
                  }}
                  type="number"
                  value={limitInput}
                />
              </label>
            </div>
          </div>
          {timeRange === "custom" ? (
            <div className="email-date-range">
              <label>开始日期<input max={customEndDate || undefined} onChange={(event) => setCustomStartDate(event.target.value)} type="date" value={customStartDate} /></label>
              <span>至</span>
              <label>结束日期<input min={customStartDate || undefined} onChange={(event) => setCustomEndDate(event.target.value)} type="date" value={customEndDate} /></label>
            </div>
          ) : null}

          <div className="email-message-list">
            {messagesQuery.isLoading ? <div className="module-empty">正在读取 QQ 收件箱...</div> : null}
            {messagesQuery.error ? <div className="inline-error">{messagesQuery.error.message}</div> : null}
            {!messagesQuery.isLoading && !messagesQuery.data?.length ? <div className="module-empty">当前范围内没有邮件。</div> : null}
            {messagesQuery.data?.map((message) => (
              <article className={`email-message-card${message.unread ? " unread" : ""}`} key={message.uid}>
                <button className="email-message-main" onClick={() => openMessage.mutate(message.uid)} type="button">
                  <div className="email-message-heading">
                    <strong>{message.subject}</strong>
                    {message.unread ? <span>未读</span> : <small>已读</small>}
                  </div>
                  <div className="email-sender">{formatSender(message.from_address)}</div>
                  <p>{message.snippet || "该邮件没有可显示的文本摘要。"}</p>
                  <time>{message.sent_at}</time>
                </button>
                <div className="email-card-actions">
                  <button onClick={() => createReply.mutate(message.uid)} type="button"><Reply size={14} />回复</button>
                  <button onClick={() => openMessage.mutate(message.uid)} type="button"><Eye size={14} />全文</button>
                </div>
              </article>
            ))}
          </div>
        </section>

        <div className="email-side-stack">
          <section className="email-detail-panel">
            <div className="email-section-title"><div><Mail size={18} /><strong>邮件全文</strong></div></div>
            {openMessage.isPending ? <div className="module-empty">正在读取邮件全文...</div> : null}
            {openMessage.error ? <div className="inline-error">{openMessage.error.message}</div> : null}
            {selectedMessage ? (
              <div className="email-detail">
                <h2>{selectedMessage.subject}</h2>
                <dl><div><dt>发件人</dt><dd>{selectedMessage.from_address}</dd></div><div><dt>时间</dt><dd>{selectedMessage.sent_at}</dd></div></dl>
                <pre>{selectedMessage.body || selectedMessage.snippet || "邮件正文为空。"}</pre>
                <button onClick={() => createReply.mutate(selectedMessage.uid)} type="button"><Reply size={15} />根据这封邮件生成回复草稿</button>
              </div>
            ) : <div className="module-empty">选择一封邮件查看完整正文。</div>}
          </section>

          <section className="email-compose-panel">
            <div className="email-section-title"><div><Send size={18} /><strong>回复 / 写邮件</strong></div></div>
            <p className="email-help">草稿在本地生成。真正发送前必须通过下方确认卡。</p>
            <label>收件人<input onChange={(event) => updateDraft("to", event.target.value)} placeholder="name@example.com" value={draft.to} /></label>
            <label>主题<input onChange={(event) => updateDraft("subject", event.target.value)} placeholder="邮件主题" value={draft.subject} /></label>
            <label>正文<textarea onChange={(event) => updateDraft("body", event.target.value)} placeholder="邮件正文" rows={7} value={draft.body} /></label>
            <button
              className="module-primary-button"
              disabled={!draft.to.trim() || !draft.body.trim() || prepareSend.isPending || Boolean(pendingAction)}
              onClick={() => prepareSend.mutate({ to: draft.to, subject: draft.subject, body: draft.body, source_message_uid: draft.source_message_uid })}
              type="button"
            ><ShieldCheck size={15} />生成发送确认</button>
            {createReply.error ? <div className="inline-error">{createReply.error.message}</div> : null}
            {prepareSend.error ? <div className="inline-error">{prepareSend.error.message}</div> : null}

            {pendingAction ? (
              <div className="email-confirm-card">
                <div><ShieldCheck size={17} /><strong>等待用户确认</strong></div>
                <dl>
                  <div><dt>收件人</dt><dd>{pendingAction.recipient}</dd></div>
                  <div><dt>主题</dt><dd>{pendingAction.subject}</dd></div>
                </dl>
                <pre>{pendingAction.body}</pre>
                <p>邮件发送后无法可靠撤回，请核对内容。</p>
                <div className="email-confirm-actions">
                  <button className="confirm" disabled={confirmSend.isPending} onClick={() => confirmSend.mutate(pendingAction.id)} type="button"><Send size={14} />确认发送</button>
                  <button disabled={cancelSend.isPending} onClick={() => cancelSend.mutate(pendingAction.id)} type="button"><X size={14} />取消</button>
                </div>
              </div>
            ) : null}
            {confirmSend.error ? <div className="inline-error">{confirmSend.error.message}</div> : null}
          </section>

          <section className="email-audit-panel">
            <div className="email-section-title"><div><Clock3 size={18} /><strong>发送审计</strong></div></div>
            {!actionsQuery.data?.length ? <p className="email-help">暂无发送动作。</p> : null}
            {actionsQuery.data?.slice(0, 5).map((action) => (
              <div className={`email-audit-row status-${action.status}`} key={action.id}>
                {action.status === "sent" ? <CheckCircle2 size={15} /> : <Clock3 size={15} />}
                <div><strong>{action.subject}</strong><span>{action.recipient}</span></div>
                <small>{statusCopy(action.status)}</small>
              </div>
            ))}
          </section>
        </div>
      </div>
    </main>
  );
}
