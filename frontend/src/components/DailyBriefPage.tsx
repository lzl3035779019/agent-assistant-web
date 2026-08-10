import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  Brain,
  CalendarDays,
  Check,
  Clock3,
  Edit3,
  ExternalLink,
  LoaderCircle,
  Mail,
  Newspaper,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  X,
} from "lucide-react";

import { api } from "../api/client";
import type {
  BriefSchedule,
  BriefScheduleCreate,
  DailyBrief,
} from "../api/types";

const PRESET_TOPICS = [
  "AI 与大模型",
  "Agentic RAG",
  "开源项目",
  "产品与创业",
  "网络安全",
  "求职与招聘",
];
const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

const emptySchedule = (): BriefScheduleCreate => ({
  name: "每日简报",
  local_time: "08:00",
  timezone: "Asia/Shanghai",
  weekdays: [0, 1, 2, 3, 4, 5, 6],
  topics: ["AI 与大模型"],
  include_email: true,
  include_calendar: true,
  include_memory: true,
  enabled: true,
});

function formatDateTime(value: string | null) {
  if (!value) return "尚未运行";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusLabel(status: DailyBrief["status"]) {
  return {
    queued: "等待执行",
    running: "正在生成",
    completed: "已完成",
    failed: "生成失败",
  }[status];
}

function topicText(topics: string[]) {
  return topics.length ? topics.join("、") : "AI 与大模型";
}

export function DailyBriefPage() {
  const queryClient = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [selectedBriefId, setSelectedBriefId] = useState<string | null>(null);
  const [scheduleForm, setScheduleForm] = useState<BriefScheduleCreate | null>(null);
  const [editingScheduleId, setEditingScheduleId] = useState<string | null>(null);
  const [customTopic, setCustomTopic] = useState("");
  const [manualTopics, setManualTopics] = useState<string[]>(["AI 与大模型"]);
  const [manualSources, setManualSources] = useState({ email: true, calendar: true, memory: true });

  const statsQuery = useQuery({
    queryKey: ["daily-brief-stats"],
    queryFn: api.getDailyBriefStats,
    refetchInterval: 15_000,
  });
  const schedulesQuery = useQuery({
    queryKey: ["brief-schedules"],
    queryFn: api.listBriefSchedules,
  });
  const briefsQuery = useQuery({
    queryKey: ["daily-briefs", unreadOnly],
    queryFn: () => api.listDailyBriefs(unreadOnly),
    refetchInterval: (query) => query.state.data?.some((item) => item.status === "queued" || item.status === "running") ? 1_200 : false,
  });
  const selectedBrief = useMemo(
    () => briefsQuery.data?.find((item) => item.id === selectedBriefId) ?? briefsQuery.data?.[0] ?? null,
    [briefsQuery.data, selectedBriefId],
  );

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["daily-brief-stats"] });
    void queryClient.invalidateQueries({ queryKey: ["brief-schedules"] });
    void queryClient.invalidateQueries({ queryKey: ["daily-briefs"] });
  };

  const createSchedule = useMutation({
    mutationFn: api.createBriefSchedule,
    onSuccess() {
      setScheduleForm(null);
      setEditingScheduleId(null);
      refresh();
    },
  });
  const updateSchedule = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: BriefScheduleCreate }) => api.updateBriefSchedule(id, payload),
    onSuccess() {
      setScheduleForm(null);
      setEditingScheduleId(null);
      refresh();
    },
  });
  const deleteSchedule = useMutation({ mutationFn: api.deleteBriefSchedule, onSuccess: refresh });
  const generate = useMutation({
    mutationFn: api.generateDailyBrief,
    onSuccess(brief) {
      setSelectedBriefId(brief.id);
      setUnreadOnly(false);
      refresh();
    },
  });
  const markRead = useMutation({
    mutationFn: api.markDailyBriefRead,
    onSuccess: refresh,
  });
  const markAllRead = useMutation({ mutationFn: api.markAllDailyBriefsRead, onSuccess: refresh });

  function editSchedule(schedule: BriefSchedule) {
    setEditingScheduleId(schedule.id);
    setScheduleForm({
      name: schedule.name,
      local_time: schedule.local_time,
      timezone: schedule.timezone,
      weekdays: schedule.weekdays,
      topics: schedule.topics,
      include_email: schedule.include_email,
      include_calendar: schedule.include_calendar,
      include_memory: schedule.include_memory,
      enabled: schedule.enabled,
    });
  }

  function submitSchedule(event: FormEvent) {
    event.preventDefault();
    if (!scheduleForm) return;
    const payload = { ...scheduleForm, name: scheduleForm.name.trim(), topics: scheduleForm.topics.length ? scheduleForm.topics : ["AI 与大模型"] };
    if (editingScheduleId) updateSchedule.mutate({ id: editingScheduleId, payload });
    else createSchedule.mutate(payload);
  }

  function toggleTopic(topic: string, target: "manual" | "schedule") {
    if (target === "manual") {
      setManualTopics((current) => current.includes(topic) ? current.filter((item) => item !== topic) : [...current, topic]);
      return;
    }
    setScheduleForm((current) => current ? {
      ...current,
      topics: current.topics.includes(topic) ? current.topics.filter((item) => item !== topic) : [...current.topics, topic],
    } : current);
  }

  function addCustomTopic() {
    const value = customTopic.trim();
    if (!value) return;
    setManualTopics((current) => current.includes(value) ? current : [...current, value]);
    setCustomTopic("");
  }

  function selectBrief(brief: DailyBrief) {
    setSelectedBriefId(brief.id);
    if (brief.unread && brief.status === "completed") markRead.mutate(brief.id);
  }

  const mutationError = createSchedule.error ?? updateSchedule.error ?? deleteSchedule.error ?? generate.error;

  return (
    <main className="brief-workspace">
      <header className="module-header brief-header">
        <div>
          <span className="eyebrow">DAILY BRIEF AGENT</span>
          <h1>每日简报</h1>
          <p>并行汇总未读邮件、今日日程、长期偏好和关注主题新闻，形成可追踪的个人信息摘要。</p>
        </div>
        <button className="module-primary-button" disabled={generate.isPending} onClick={() => generate.mutate({ topics: manualTopics, include_email: manualSources.email, include_calendar: manualSources.calendar, include_memory: manualSources.memory })} type="button">
          {generate.isPending ? <LoaderCircle className="spin" size={16} /> : <Newspaper size={16} />}立即生成
        </button>
      </header>

      <div className="brief-content">
        <section className="brief-overview">
          <div><Bell size={17} /><span>未读简报</span><strong>{statsQuery.data?.unread_count ?? 0}</strong></div>
          <div><Newspaper size={17} /><span>历史简报</span><strong>{statsQuery.data?.total_count ?? 0}</strong></div>
          <div><Clock3 size={17} /><span>启用计划</span><strong>{statsQuery.data?.active_schedule_count ?? 0}</strong></div>
          <div className={statsQuery.data?.generating_count ? "active" : ""}><RefreshCw className={statsQuery.data?.generating_count ? "spin" : ""} size={17} /><span>生成中</span><strong>{statsQuery.data?.generating_count ?? 0}</strong></div>
        </section>

        <section className="brief-control-grid">
          <div className="brief-panel">
            <div className="brief-section-heading"><div><Clock3 size={17} /><div><h2>定时简报计划</h2><p>支持一天多个计划，后台任务不会因页面切换而中断。</p></div></div><button className="icon-action" onClick={() => { setEditingScheduleId(null); setScheduleForm(emptySchedule()); }} title="新增计划" type="button"><Plus size={16} /></button></div>
            <div className="brief-schedule-list">
              {schedulesQuery.data?.map((schedule) => (
                <article className={`brief-schedule-row${schedule.enabled ? "" : " disabled"}`} key={schedule.id}>
                  <div className="brief-time"><strong>{schedule.local_time}</strong><span>{schedule.enabled ? "运行中" : "已停用"}</span></div>
                  <div className="brief-schedule-copy"><strong>{schedule.name}</strong><span>周{schedule.weekdays.map((day) => WEEKDAYS[day]).join("、")} · {topicText(schedule.topics)}</span><small>下次：{formatDateTime(schedule.next_run_at)}</small></div>
                  <div className="brief-row-actions">
                    <button onClick={() => generate.mutate({ schedule_id: schedule.id, topics: [], include_email: true, include_calendar: true, include_memory: true })} title="立即运行一次" type="button"><Newspaper size={14} /></button>
                    <button onClick={() => editSchedule(schedule)} title="修改计划" type="button"><Edit3 size={14} /></button>
                    <button onClick={() => updateSchedule.mutate({ id: schedule.id, payload: { ...schedule, enabled: !schedule.enabled } })} title={schedule.enabled ? "停用计划" : "启用计划"} type="button">{schedule.enabled ? <X size={14} /> : <Check size={14} />}</button>
                    <button className="danger" onClick={() => window.confirm(`删除计划“${schedule.name}”？`) && deleteSchedule.mutate(schedule.id)} title="删除计划" type="button"><Trash2 size={14} /></button>
                  </div>
                </article>
              ))}
              {!schedulesQuery.isLoading && !schedulesQuery.data?.length ? <div className="brief-empty">尚未创建定时计划。</div> : null}
            </div>
          </div>

          <div className="brief-panel brief-manual-panel">
            <div className="brief-section-heading"><div><Settings2 size={17} /><div><h2>本次简报范围</h2><p>设置仅作用于手动生成，不会修改定时计划。</p></div></div></div>
            <span className="field-caption">关注主题</span>
            <div className="topic-picker">
              {PRESET_TOPICS.map((topic) => <button className={manualTopics.includes(topic) ? "selected" : ""} key={topic} onClick={() => toggleTopic(topic, "manual")} type="button">{manualTopics.includes(topic) ? <Check size={12} /> : null}{topic}</button>)}
            </div>
            <div className="custom-topic"><input onChange={(event) => setCustomTopic(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addCustomTopic(); } }} placeholder="添加自定义主题" value={customTopic} /><button onClick={addCustomTopic} title="添加主题" type="button"><Plus size={15} /></button></div>
            {manualTopics.filter((item) => !PRESET_TOPICS.includes(item)).length ? <div className="custom-topic-list">{manualTopics.filter((item) => !PRESET_TOPICS.includes(item)).map((topic) => <button key={topic} onClick={() => toggleTopic(topic, "manual")} type="button">{topic}<X size={11} /></button>)}</div> : null}
            <span className="field-caption">数据来源</span>
            <div className="source-toggles">
              <label><input checked={manualSources.email} onChange={(event) => setManualSources({ ...manualSources, email: event.target.checked })} type="checkbox" /><Mail size={14} />未读邮件</label>
              <label><input checked={manualSources.calendar} onChange={(event) => setManualSources({ ...manualSources, calendar: event.target.checked })} type="checkbox" /><CalendarDays size={14} />日程与待办</label>
              <label><input checked={manualSources.memory} onChange={(event) => setManualSources({ ...manualSources, memory: event.target.checked })} type="checkbox" /><Brain size={14} />长期偏好</label>
              <label className="fixed"><Search size={14} />主题新闻</label>
            </div>
          </div>
        </section>

        {scheduleForm ? (
          <form className="brief-schedule-editor" onSubmit={submitSchedule}>
            <div className="brief-editor-heading"><div><Clock3 size={17} /><strong>{editingScheduleId ? "修改简报计划" : "新增简报计划"}</strong></div><button onClick={() => { setScheduleForm(null); setEditingScheduleId(null); }} title="关闭" type="button"><X size={16} /></button></div>
            <label>计划名称<input onChange={(event) => setScheduleForm({ ...scheduleForm, name: event.target.value })} required value={scheduleForm.name} /></label>
            <label>生成时间<input onChange={(event) => setScheduleForm({ ...scheduleForm, local_time: event.target.value })} required type="time" value={scheduleForm.local_time} /></label>
            <label>时区<select onChange={(event) => setScheduleForm({ ...scheduleForm, timezone: event.target.value })} value={scheduleForm.timezone}><option value="Asia/Shanghai">Asia/Shanghai</option><option value="Asia/Hong_Kong">Asia/Hong_Kong</option></select></label>
            <div className="wide"><span className="field-caption">执行日期</span><div className="weekday-picker">{WEEKDAYS.map((day, index) => <button className={scheduleForm.weekdays.includes(index) ? "selected" : ""} key={day} onClick={() => setScheduleForm({ ...scheduleForm, weekdays: scheduleForm.weekdays.includes(index) ? scheduleForm.weekdays.filter((item) => item !== index) : [...scheduleForm.weekdays, index].sort() })} type="button">{day}</button>)}</div></div>
            <div className="wide"><span className="field-caption">关注主题</span><div className="topic-picker">{PRESET_TOPICS.map((topic) => <button className={scheduleForm.topics.includes(topic) ? "selected" : ""} key={topic} onClick={() => toggleTopic(topic, "schedule")} type="button">{topic}</button>)}</div></div>
            <div className="wide source-toggles"><label><input checked={scheduleForm.include_email} onChange={(event) => setScheduleForm({ ...scheduleForm, include_email: event.target.checked })} type="checkbox" />邮件</label><label><input checked={scheduleForm.include_calendar} onChange={(event) => setScheduleForm({ ...scheduleForm, include_calendar: event.target.checked })} type="checkbox" />日程</label><label><input checked={scheduleForm.include_memory} onChange={(event) => setScheduleForm({ ...scheduleForm, include_memory: event.target.checked })} type="checkbox" />记忆</label><label><input checked={scheduleForm.enabled} onChange={(event) => setScheduleForm({ ...scheduleForm, enabled: event.target.checked })} type="checkbox" />启用计划</label></div>
            <button className="module-primary-button wide" disabled={createSchedule.isPending || updateSchedule.isPending} type="submit"><Check size={15} />保存计划</button>
          </form>
        ) : null}
        {mutationError ? <div className="inline-error">{mutationError.message}</div> : null}

        <section className="brief-inbox-layout">
          <div className="brief-inbox">
            <div className="brief-inbox-heading"><div><Bell size={17} /><div><h2>简报收件箱</h2><p>{statsQuery.data?.unread_count ?? 0} 条未读</p></div></div><div><label><input checked={unreadOnly} onChange={(event) => setUnreadOnly(event.target.checked)} type="checkbox" />只看未读</label><button disabled={!statsQuery.data?.unread_count} onClick={() => markAllRead.mutate()} type="button">全部已读</button></div></div>
            <div className="brief-list">
              {briefsQuery.data?.map((brief) => (
                <button className={`${selectedBrief?.id === brief.id ? "selected" : ""}${brief.unread ? " unread" : ""}`} key={brief.id} onClick={() => selectBrief(brief)} type="button">
                  <span className={`brief-status status-${brief.status}`}>{brief.status === "running" || brief.status === "queued" ? <LoaderCircle className="spin" size={14} /> : brief.status === "failed" ? <AlertTriangle size={14} /> : <Newspaper size={14} />}</span>
                  <span><strong>{brief.unread ? "未读 · " : ""}{brief.title}</strong><small>{statusLabel(brief.status)} · {formatDateTime(brief.created_at)}</small><em>{topicText(brief.topics)}</em></span>
                </button>
              ))}
              {!briefsQuery.isLoading && !briefsQuery.data?.length ? <div className="brief-empty">当前没有符合条件的简报。</div> : null}
            </div>
          </div>

          <article className="brief-reader">
            {!selectedBrief ? <div className="brief-reader-empty"><Newspaper size={24} /><strong>选择一份简报查看详情</strong><span>也可以点击“立即生成”创建第一份简报。</span></div> : (
              <>
                <header><div><span className="eyebrow">{selectedBrief.source === "scheduled" ? "SCHEDULED BRIEF" : "MANUAL BRIEF"}</span><h2>{selectedBrief.title}</h2><p>{formatDateTime(selectedBrief.completed_at ?? selectedBrief.created_at)} · {topicText(selectedBrief.topics)}</p></div><span className={`reader-state status-${selectedBrief.status}`}>{statusLabel(selectedBrief.status)}</span></header>
                {selectedBrief.status === "queued" || selectedBrief.status === "running" ? <div className="brief-generating"><LoaderCircle className="spin" size={20} /><div><strong>Daily Brief Agent 正在工作</strong><span>邮件、日历、记忆与新闻采集会并行执行，完成后此处自动更新。</span></div></div> : null}
                {selectedBrief.status === "failed" ? <div className="inline-error">{selectedBrief.error}</div> : null}
                {selectedBrief.status === "completed" ? <BriefContent brief={selectedBrief} /> : null}
              </>
            )}
          </article>
        </section>
      </div>
    </main>
  );
}

function BriefContent({ brief }: { brief: DailyBrief }) {
  const sections = brief.sections;
  return (
    <div className="brief-reader-content">
      <section className="brief-summary"><strong>今日概览</strong><p>{sections.summary || "本次简报已完成。"}</p></section>
      <section><h3>今日重点</h3><ul>{sections.priorities?.map((item) => <li key={item}>{item}</li>)}</ul></section>
      <section><h3><Mail size={17} />邮件</h3>{sections.email?.length ? <div className="brief-item-list">{sections.email.map((item) => <article key={item.uid}><strong>{item.subject}</strong><span>{item.from} · {item.sent_at}</span><p>{item.snippet}</p></article>)}</div> : <p className="brief-section-empty">没有需要处理的未读邮件。</p>}</section>
      <section><h3><CalendarDays size={17} />日程与待办</h3>{sections.calendar?.length ? <div className="brief-item-list compact">{sections.calendar.map((item, index) => <article key={`${item.kind}-${item.title}-${index}`}><strong>{item.title}</strong><span>{item.kind === "event" ? `${formatDateTime(item.start_at ?? null)}${item.location ? ` · ${item.location}` : ""}` : `${item.due_at ? `截止 ${formatDateTime(item.due_at)}` : "无截止时间"}${item.overdue ? " · 已逾期" : ""}`}</span></article>)}</div> : <p className="brief-section-empty">未来 24 小时没有日程或待办。</p>}</section>
      <section><h3><Search size={17} />值得关注</h3>{sections.news?.length ? <div className="brief-news-list">{sections.news.map((item, index) => <a href={item.url} key={`${item.url}-${index}`} rel="noreferrer" target="_blank"><span>{item.topic}</span><strong>{item.title}<ExternalLink size={13} /></strong><p>{item.snippet}</p></a>)}</div> : <p className="brief-section-empty">没有获取到关注主题新闻。</p>}</section>
      {sections.memory?.length ? <section><h3><Brain size={17} />个性化依据</h3><div className="brief-memory-list">{sections.memory.map((item, index) => <span key={`${item.type}-${index}`}>{item.content}</span>)}</div></section> : null}
      {sections.warnings?.length ? <section className="brief-warnings"><h3><AlertTriangle size={17} />数据源提示</h3>{sections.warnings.map((item) => <p key={item}>{item}</p>)}</section> : null}
    </div>
  );
}
