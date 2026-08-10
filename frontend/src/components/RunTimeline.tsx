import { Check, GitBranch, LoaderCircle, X } from "lucide-react";

import type { RunEvent } from "../api/types";

const eventLabels: Record<string, string> = {
  run_started: "任务开始",
  supervisor_decision: "Supervisor 完成决策",
  agent_message: "Agent 消息",
  agent_retry: "子任务重试",
  agent_started: "子 Agent 开始执行",
  agent_progress: "执行进度更新",
  agent_completed: "子 Agent 执行完成",
  run_completed: "任务完成",
  run_failed: "任务失败",
};

const stageCopy: Record<string, { title: string; summary: string }> = {
  analyze: { title: "理解问题", summary: "规范化用户问题并确定知识检索目标" },
  retrieve: { title: "检索知识库", summary: "执行关键词与向量混合检索" },
  grade: { title: "评估证据", summary: "检查证据的数量、相关度和覆盖度" },
  expand: { title: "补充检索", summary: "扩展查询词并补充缺失证据" },
  synthesize: { title: "生成回答", summary: "基于已验证证据生成带引用回答" },
  research_analyze: { title: "分析研究目标", summary: "拆解研究目标并规划互补查询" },
  research_search: { title: "并行检索网络资料", summary: "从多个检索方向收集实时网络证据" },
  research_evaluate: { title: "评估网络证据", summary: "检查来源多样性、相关度与覆盖度" },
  research_supplement: { title: "补充网络检索", summary: "根据证据缺口生成补充查询" },
  research_synthesize: { title: "形成研究结论", summary: "基于网络证据生成带引用结论" },
  memory_retrieve: { title: "检索长期记忆", summary: "筛选与当前请求相关的稳定用户信息" },
  memory_extract: { title: "提取候选记忆", summary: "识别用户画像、稳定偏好、项目事实和长期指令" },
  memory_validate: { title: "验证候选记忆", summary: "过滤敏感信息、短期事实和一次性任务" },
  memory_update: { title: "更新长期记忆", summary: "去重并持久化通过安全校验的记忆" },
  email_analyze: { title: "分析邮件目标", summary: "判断本轮需要读取、筛选还是生成回复草稿" },
  email_fetch: { title: "读取邮件", summary: "通过 IMAP 只读连接获取邮件内容" },
  email_triage: { title: "筛选邮件优先级", summary: "识别未读、重要和需要行动的邮件" },
  email_compose: { title: "形成邮件结果", summary: "生成邮件摘要或可编辑回复草稿" },
  calendar_analyze: { title: "分析日历任务", summary: "判断是查询还是规划待确认变更" },
  calendar_retrieve: { title: "读取日程与待办", summary: "读取查询窗口内的日程和未完成待办" },
  calendar_plan: { title: "规划日历动作", summary: "执行参数校验与冲突检查，生成 pending 动作" },
  calendar_summarize: { title: "形成日历结果", summary: "汇总日程、待办和待确认动作" },
  brief_analyze: { title: "分析简报配置", summary: "确定关注主题和本轮需要聚合的数据源" },
  brief_collect: { title: "并行收集简报数据", summary: "同时读取邮件、日历、记忆和关注主题新闻" },
  brief_prioritize: { title: "评估今日优先级", summary: "提取需要关注和行动的事项" },
  brief_compose: { title: "生成每日简报", summary: "整理为可阅读、可追溯的 Markdown 简报" },
  monitor_analyze: { title: "分析监控规则", summary: "确定监控对象、数据源与历史基线" },
  monitor_collect: { title: "采集当前快照", summary: "从 GitHub API 或联网搜索获取最新信息" },
  monitor_compare: { title: "比较历史基线", summary: "识别相对上次检查出现的新增变化" },
  monitor_notify: { title: "更新基线与通知", summary: "保存快照并为重要新增变化创建通知" },
};

const metricLabels: Record<string, string> = {
  query: "查询",
  evidence_count: "证据",
  document_count: "文档",
  top_score: "最高相关度",
  confidence: "置信度",
  decision: "判断",
  attempt: "重试轮次",
  answer_length: "回答字数",
  citation_count: "引用",
  query_count: "查询",
  source_count: "来源",
  gap_count: "证据缺口",
  research_rounds: "研究轮次",
  attempts: "执行次数",
  runtime_duration_ms: "Runtime 耗时",
  memory_count: "相关记忆",
  memory_types: "记忆类型",
  candidate_count: "候选记忆",
  accepted_count: "通过校验",
  rejected_count: "拒绝写入",
  saved_count: "保存记忆",
  email_count: "邮件",
  unread_count: "未读",
  important_count: "重要邮件",
  draft_count: "草稿",
  email_operation: "邮件操作",
  calendar_event_count: "日程",
  todo_count: "待办",
  pending_action_count: "待确认动作",
  conflict_count: "时间冲突",
  calendar_operation: "日历操作",
  topic_count: "关注主题",
  calendar_item_count: "日历事项",
  news_count: "新闻",
  priority_count: "今日重点",
  warning_count: "数据源警告",
  monitor_item_count: "本轮结果",
  baseline_count: "历史基线",
  change_count: "新增变化",
  notification_count: "新通知",
  monitor_type: "监控类型",
};

const agentLabels: Record<string, string> = {
  system: "System",
  supervisor: "Supervisor",
  knowledge: "Knowledge Agent",
  web_research: "Web Research Agent",
  memory: "Memory Agent",
  email: "Email Agent",
  calendar: "Calendar / Task Agent",
  daily_brief: "Daily Brief Agent",
  information_monitor: "Monitor Agent",
};

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function eventTitle(event: RunEvent): string {
  const title = textValue(event.payload.title);
  if (title) return title;
  const node = textValue(event.payload.node);
  if (event.event_type === "agent_progress" && node && stageCopy[node]) return stageCopy[node].title;
  return eventLabels[event.event_type] ?? event.event_type;
}

function eventSummary(event: RunEvent): string | null {
  const summary = textValue(event.payload.summary);
  if (summary) return summary;
  const node = textValue(event.payload.node);
  if (event.event_type === "agent_progress" && node && stageCopy[node]) return stageCopy[node].summary;
  if (event.event_type === "run_started") return "已接收任务并创建可追踪执行实例";
  return null;
}

function eventMetrics(event: RunEvent): Array<{ label: string; value: string }> {
  const source = event.payload.metrics;
  const metrics = source && typeof source === "object" && !Array.isArray(source)
    ? source as Record<string, unknown>
    : event.payload;
  return Object.entries(metrics).flatMap(([key, value]) => {
    if (!(key in metricLabels)) return [];
    if (key === "confidence" || key === "top_score") {
      const number = numberValue(value);
      return number === null ? [] : [{ label: metricLabels[key], value: `${Math.round(number * 100)}%` }];
    }
    const display = typeof value === "number" || typeof value === "string" ? String(value) : "";
    if (!display) return [];
    const suffix = key === "evidence_count" || key === "source_count" ? " 条" : key === "document_count" ? " 个" : key === "citation_count" ? " 处" : key === "runtime_duration_ms" ? " ms" : "";
    return [{ label: metricLabels[key], value: `${display}${suffix}` }];
  });
}

interface Props {
  events: RunEvent[];
  running: boolean;
}

export function RunTimeline({ events, running }: Props) {
  if (!events.length && !running) {
    return (
      <div className="empty-trace">
        <GitBranch size={20} />
        <div>
          <strong>执行轨迹将在这里显示</strong>
          <span>提交任务后可查看 Supervisor 与子 Agent 状态。</span>
        </div>
      </div>
    );
  }

  return (
    <div className="timeline">
      {events.map((event) => {
        const failed = event.event_type === "run_failed";
        const summary = eventSummary(event);
        const metrics = eventMetrics(event);
        const duration = numberValue(event.payload.duration_ms);
        return (
          <div className="timeline-row" key={event.id}>
            <span className={`timeline-icon${failed ? " failed" : " done"}`}>
              {failed ? <X size={13} /> : <Check size={13} />}
            </span>
            <div className="timeline-content">
              <div className="timeline-heading">
                <strong>{eventTitle(event)}</strong>
                <small>{agentLabels[event.agent_id] ?? event.agent_id} · #{event.sequence}{duration !== null ? ` · ${duration} ms` : ""}</small>
              </div>
              {summary ? <p>{summary}</p> : null}
              {metrics.length ? (
                <div className="timeline-metrics">
                  {metrics.map((metric) => <span key={`${event.id}-${metric.label}`}><b>{metric.label}</b>{metric.value}</span>)}
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
      {running ? (
        <div className="timeline-row live">
          <span className="timeline-icon"><LoaderCircle size={13} className="spin" /></span>
          <div className="timeline-content"><strong>正在等待后续事件</strong><p>SSE 实时连接保持中，新的执行状态会自动追加。</p></div>
        </div>
      ) : null}
    </div>
  );
}
