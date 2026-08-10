import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Check,
  Edit3,
  ExternalLink,
  Eye,
  FileClock,
  Github,
  LoaderCircle,
  Newspaper,
  Play,
  Plus,
  Radar,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";

import { api } from "../api/client";
import type {
  MonitorNotification,
  MonitorResult,
  MonitorRule,
  MonitorRuleCreate,
  MonitorTargetType,
} from "../api/types";

const EMPTY_RULE: MonitorRuleCreate = {
  name: "",
  target_type: "news",
  query: "",
  interval_minutes: 360,
  enabled: true,
};

const RESULT_PAGE_SIZE = 9;

const PRESETS: Array<MonitorRuleCreate & { caption: string }> = [
  { name: "AI 与大模型动态", target_type: "news", query: "AI agent 大模型 最新重要发布", interval_minutes: 360, enabled: true, caption: "新闻" },
  { name: "热门 AI 开源项目", target_type: "github", query: "topic:artificial-intelligence stars:>5000", interval_minutes: 720, enabled: true, caption: "GitHub" },
  { name: "目标公司动态", target_type: "company", query: "目标公司 产品发布 招聘 融资 最新动态", interval_minutes: 720, enabled: true, caption: "公司" },
  { name: "技术博客更新", target_type: "blog", query: "AI engineering agentic RAG 技术博客 最新文章", interval_minutes: 720, enabled: true, caption: "博客" },
];

const TYPE_LABELS: Record<MonitorTargetType, string> = {
  news: "新闻资讯",
  github: "GitHub 项目",
  company: "公司动态",
  blog: "技术博客",
};

function formatDate(value: string | null) {
  if (!value) return "尚未运行";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusLabel(status: string) {
  return ({ never: "待建立基线", queued: "等待执行", running: "检查中", completed: "已完成", failed: "失败" } as Record<string, string>)[status] ?? status;
}

export function MonitorPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<MonitorRuleCreate | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [selectedNotification, setSelectedNotification] = useState<MonitorNotification | null>(null);
  const [selectedResult, setSelectedResult] = useState<MonitorResult | null>(null);
  const [resultRuleFilter, setResultRuleFilter] = useState("");
  const [resultPage, setResultPage] = useState(0);

  const rulesQuery = useQuery({
    queryKey: ["monitor-rules"],
    queryFn: api.listMonitorRules,
    refetchInterval: (query) => query.state.data?.some((rule) => ["queued", "running"].includes(rule.last_run_status)) ? 1500 : 20_000,
  });
  const statsQuery = useQuery({
    queryKey: ["monitor-stats"],
    queryFn: api.getMonitorStats,
    refetchInterval: 10_000,
  });
  const notificationsQuery = useQuery({
    queryKey: ["monitor-notifications", unreadOnly],
    queryFn: () => api.listMonitorNotifications(unreadOnly),
    refetchInterval: 15_000,
  });
  const resultsQuery = useQuery({
    queryKey: ["monitor-results", resultRuleFilter, resultPage],
    queryFn: () => api.listMonitorResults(resultRuleFilter || undefined, RESULT_PAGE_SIZE, resultPage * RESULT_PAGE_SIZE),
    refetchInterval: rulesQuery.data?.some((rule) => ["queued", "running"].includes(rule.last_run_status)) ? 1500 : 20_000,
  });

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["monitor-rules"] }),
      queryClient.invalidateQueries({ queryKey: ["monitor-stats"] }),
      queryClient.invalidateQueries({ queryKey: ["monitor-notifications"] }),
      queryClient.invalidateQueries({ queryKey: ["monitor-results"] }),
    ]);
  };
  const createRule = useMutation({ mutationFn: api.createMonitorRule, onSuccess: () => { setForm(null); void refresh(); } });
  const updateRule = useMutation({ mutationFn: ({ id, payload }: { id: string; payload: Partial<MonitorRuleCreate> }) => api.updateMonitorRule(id, payload), onSuccess: () => { setForm(null); setEditingId(null); void refresh(); } });
  const deleteRule = useMutation({ mutationFn: api.deleteMonitorRule, onSuccess: refresh });
  const runRule = useMutation({ mutationFn: api.runMonitorRule, onSuccess: refresh });
  const markRead = useMutation({ mutationFn: api.markMonitorNotificationRead, onSuccess: refresh });
  const markAllRead = useMutation({ mutationFn: api.markAllMonitorNotificationsRead, onSuccess: refresh });
  const deleteResult = useMutation({ mutationFn: api.deleteMonitorResult, onSuccess: () => { if (resultPage > 0 && resultsQuery.data?.items.length === 1) setResultPage(resultPage - 1); void refresh(); } });
  const clearResults = useMutation({ mutationFn: api.clearMonitorResults, onSuccess: () => { setResultPage(0); void refresh(); } });
  const error = createRule.error ?? updateRule.error ?? deleteRule.error ?? runRule.error ?? deleteResult.error ?? clearResults.error;

  const runningRules = useMemo(
    () => rulesQuery.data?.filter((rule) => ["queued", "running"].includes(rule.last_run_status)).length ?? 0,
    [rulesQuery.data],
  );

  function editRule(rule: MonitorRule) {
    setEditingId(rule.id);
    setForm({ name: rule.name, target_type: rule.target_type, query: rule.query, interval_minutes: rule.interval_minutes, enabled: rule.enabled });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    if (editingId) updateRule.mutate({ id: editingId, payload: form });
    else createRule.mutate(form);
  }

  return (
    <main className="monitor-workspace">
      <header className="monitor-header">
        <div><span className="eyebrow">MONITOR AGENT</span><h1>信息监控</h1><p>持续跟踪指定主题，以基线对比识别真正的新增变化。</p></div>
        <button className="module-primary-button" onClick={() => { setEditingId(null); setForm({ ...EMPTY_RULE }); }} type="button"><Plus size={15} />新建规则</button>
      </header>

      <div className="monitor-content">
        <section className="monitor-overview" aria-label="监控概览">
          <div><Radar size={17} /><span>监控规则</span><strong>{statsQuery.data?.rule_count ?? 0}</strong></div>
          <div><Check size={17} /><span>已启用</span><strong>{statsQuery.data?.enabled_count ?? 0}</strong></div>
          <div className={runningRules ? "active" : ""}><RefreshCw className={runningRules ? "spin" : ""} size={17} /><span>执行中</span><strong>{statsQuery.data?.running_count ?? 0}</strong></div>
          <div><Bell size={17} /><span>未读变化</span><strong>{statsQuery.data?.unread_count ?? 0}</strong></div>
        </section>

        {!rulesQuery.data?.length && !rulesQuery.isLoading ? (
          <section className="monitor-presets">
            <div><h2>从常用规则开始</h2><p>选择模板后仍可修改查询词和检查间隔。</p></div>
            <div>{PRESETS.map((preset) => <button key={preset.name} onClick={() => { setEditingId(null); setForm({ ...preset }); }} type="button"><span>{preset.target_type === "github" ? <Github size={16} /> : <Newspaper size={16} />}{preset.caption}</span><strong>{preset.name}</strong><small>{preset.query}</small></button>)}</div>
          </section>
        ) : null}

        {form ? (
          <form className="monitor-editor" onSubmit={submit}>
            <div className="monitor-editor-heading"><strong>{editingId ? "修改监控规则" : "新建监控规则"}</strong><button onClick={() => { setForm(null); setEditingId(null); }} title="关闭" type="button"><X size={16} /></button></div>
            <label>规则名称<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label>监控类型<select value={form.target_type} onChange={(event) => setForm({ ...form, target_type: event.target.value as MonitorTargetType })}>{Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="wide">查询目标<textarea required rows={3} value={form.query} onChange={(event) => setForm({ ...form, query: event.target.value })} /></label>
            <label>检查间隔<select value={form.interval_minutes} onChange={(event) => setForm({ ...form, interval_minutes: Number(event.target.value) })}><option value={60}>每小时</option><option value={360}>每 6 小时</option><option value={720}>每 12 小时</option><option value={1440}>每天</option><option value={10080}>每周</option></select></label>
            <label className="monitor-check"><input checked={form.enabled} type="checkbox" onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />保存后启用定时检查</label>
            <button className="module-primary-button wide" disabled={createRule.isPending || updateRule.isPending} type="submit"><Check size={15} />保存规则</button>
          </form>
        ) : null}
        {error ? <div className="inline-error">{error.message}</div> : null}

        <section className="monitor-layout">
          <div className="monitor-rules-panel">
            <div className="monitor-section-heading"><div><Radar size={17} /><div><h2>监控规则</h2><p>首次运行建立基线，后续只提醒新增内容。</p></div></div></div>
            <div className="monitor-rule-list">
              {rulesQuery.data?.map((rule) => (
                <article className={`monitor-rule${rule.enabled ? "" : " disabled"}`} key={rule.id}>
                  <div className="monitor-rule-top"><span>{TYPE_LABELS[rule.target_type]}</span><em className={`monitor-status status-${rule.last_run_status}`}>{statusLabel(rule.last_run_status)}</em></div>
                  <h3>{rule.name}</h3><p>{rule.query}</p>
                  <div className="monitor-rule-meta"><span>每 {rule.interval_minutes >= 1440 ? `${Math.round(rule.interval_minutes / 1440)} 天` : `${Math.round(rule.interval_minutes / 60)} 小时`}</span><span>上次：{formatDate(rule.last_run_at)}</span><span>{rule.last_result.length} 条快照</span></div>
                  {rule.last_error ? <div className="monitor-rule-error">{rule.last_error}</div> : null}
                  <div className="monitor-rule-actions">
                    <button disabled={["queued", "running"].includes(rule.last_run_status)} onClick={() => runRule.mutate(rule.id)} title="立即运行一次" type="button">{["queued", "running"].includes(rule.last_run_status) ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />}立即运行</button>
                    <button onClick={() => editRule(rule)} title="修改规则" type="button"><Edit3 size={14} />修改</button>
                    <button onClick={() => updateRule.mutate({ id: rule.id, payload: { enabled: !rule.enabled } })} type="button">{rule.enabled ? <X size={14} /> : <Check size={14} />}{rule.enabled ? "停用" : "启用"}</button>
                    <button className="danger" onClick={() => window.confirm(`删除监控规则“${rule.name}”？`) && deleteRule.mutate(rule.id)} title="删除规则" type="button"><Trash2 size={14} />删除</button>
                  </div>
                </article>
              ))}
              {!rulesQuery.isLoading && !rulesQuery.data?.length ? <div className="monitor-empty">还没有监控规则。选择上方模板或新建一条规则。</div> : null}
            </div>
          </div>

          <aside className="monitor-notifications">
            <div className="monitor-notification-heading"><div><Bell size={17} /><div><h2>变化通知</h2><p>{statsQuery.data?.unread_count ?? 0} 条未读</p></div></div><button disabled={!statsQuery.data?.unread_count} onClick={() => markAllRead.mutate()} type="button">全部已读</button></div>
            <label className="monitor-unread-filter"><input checked={unreadOnly} onChange={(event) => setUnreadOnly(event.target.checked)} type="checkbox" />只看未读</label>
            <div className="monitor-notification-list">
              {notificationsQuery.data?.map((notification) => (
                <button className={notification.unread ? "unread" : ""} key={notification.id} onClick={() => { setSelectedNotification(notification); if (notification.unread) markRead.mutate(notification.id); }} type="button"><strong>{notification.title}</strong><span>{notification.summary}</span><small>{formatDate(notification.created_at)}</small></button>
              ))}
              {!notificationsQuery.isLoading && !notificationsQuery.data?.length ? <div className="monitor-empty">暂无变化通知。</div> : null}
            </div>
          </aside>
        </section>

        <section className="monitor-results-panel">
          <div className="monitor-results-heading">
            <div><FileClock size={17} /><div><h2>监控结果</h2><p>每次检查生成一张独立记录卡片，不再塞进规则卡片。</p></div></div>
            <div className="monitor-results-tools">
              <span className="monitor-result-total">共 {resultsQuery.data?.total ?? 0} 条</span>
              <select aria-label="按规则筛选结果" value={resultRuleFilter} onChange={(event) => { setResultRuleFilter(event.target.value); setResultPage(0); }}>
                <option value="">全部规则</option>
                {rulesQuery.data?.map((rule) => <option key={rule.id} value={rule.id}>{rule.name}</option>)}
              </select>
              <button disabled={!resultsQuery.data?.total || clearResults.isPending} onClick={() => window.confirm(resultRuleFilter ? "清空该规则的全部监控结果？" : "清空全部监控结果？") && clearResults.mutate(resultRuleFilter || undefined)} type="button"><Trash2 size={14} />清空历史</button>
            </div>
          </div>
          <div className="monitor-result-cards">
            {resultsQuery.data?.items.map((result) => (
              <article className="monitor-result-card" key={result.id}>
                <div className="monitor-result-card-top"><span>{TYPE_LABELS[result.target_type]}</span><time>{formatDate(result.created_at)}</time></div>
                <h3>{result.rule_name}</h3>
                <p>{result.summary}</p>
                <div className="monitor-result-metrics">
                  <span>{result.item_count} 条快照</span>
                  <span className={result.change_count ? "changed" : ""}>{result.change_count} 项变化</span>
                  {result.baseline_created ? <span>首次基线</span> : null}
                </div>
                <div className="monitor-result-actions">
                  <button onClick={() => setSelectedResult(result)} type="button"><Eye size={14} />查看详情</button>
                  <button className="danger" onClick={() => window.confirm(`删除“${result.rule_name}”的本次监控结果？`) && deleteResult.mutate(result.id)} type="button"><Trash2 size={14} />删除</button>
                </div>
              </article>
            ))}
            {!resultsQuery.isLoading && !resultsQuery.data?.items.length ? <div className="monitor-empty">暂无监控结果。立即运行一条规则后，完整结果会保存在这里。</div> : null}
          </div>
          {(resultsQuery.data?.total ?? 0) > RESULT_PAGE_SIZE ? <nav aria-label="监控结果分页" className="monitor-result-pagination"><button disabled={resultPage === 0} onClick={() => setResultPage((page) => Math.max(0, page - 1))} type="button">上一页</button><span>第 {resultPage + 1} / {Math.ceil((resultsQuery.data?.total ?? 0) / RESULT_PAGE_SIZE)} 页</span><button disabled={(resultPage + 1) * RESULT_PAGE_SIZE >= (resultsQuery.data?.total ?? 0)} onClick={() => setResultPage((page) => page + 1)} type="button">下一页</button></nav> : null}
        </section>
      </div>

      {selectedNotification ? <div className="monitor-dialog-backdrop" role="presentation" onMouseDown={() => setSelectedNotification(null)}><section aria-modal="true" className="monitor-dialog" onMouseDown={(event) => event.stopPropagation()} role="dialog"><header><div><span className="eyebrow">MONITOR UPDATE</span><h2>{selectedNotification.title}</h2><p>{formatDate(selectedNotification.created_at)}</p></div><button onClick={() => setSelectedNotification(null)} title="关闭" type="button"><X size={17} /></button></header><p>{selectedNotification.summary}</p><div className="monitor-dialog-items">{selectedNotification.payload.items?.map((item, index) => <a href={item.url} key={`${item.url}-${index}`} rel="noreferrer" target="_blank"><strong>{item.title}</strong><span>{item.summary}</span><ExternalLink size={14} /></a>)}</div></section></div> : null}
      {selectedResult ? <div className="monitor-dialog-backdrop" role="presentation" onMouseDown={() => setSelectedResult(null)}><section aria-modal="true" className="monitor-dialog" onMouseDown={(event) => event.stopPropagation()} role="dialog"><header><div><span className="eyebrow">MONITOR RESULT</span><h2>{selectedResult.rule_name}</h2><p>{formatDate(selectedResult.created_at)} · {selectedResult.item_count} 条快照 · {selectedResult.change_count} 项变化</p></div><button onClick={() => setSelectedResult(null)} title="关闭" type="button"><X size={17} /></button></header><p>{selectedResult.summary}</p><div className="monitor-dialog-items">{selectedResult.payload.items?.map((item, index) => <a href={item.url} key={`${item.url}-${index}`} rel="noreferrer" target="_blank"><strong>{item.title || "未命名结果"}</strong><span>{item.summary}</span><ExternalLink size={14} /></a>)}</div></section></div> : null}
    </main>
  );
}
