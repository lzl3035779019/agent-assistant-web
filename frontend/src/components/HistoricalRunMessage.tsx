import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, Network } from "lucide-react";

import { api } from "../api/client";
import type { ConversationMessage } from "../api/types";
import { RunTimeline } from "./RunTimeline";

interface Props {
  message: ConversationMessage;
}

export function HistoricalRunMessage({ message }: Props) {
  const [expanded, setExpanded] = useState(false);
  const runId = message.run_id;
  const eventsQuery = useQuery({
    queryKey: ["run-events", runId],
    queryFn: () => api.listRunEvents(runId!),
    enabled: expanded && Boolean(runId),
    staleTime: Number.POSITIVE_INFINITY,
  });

  if (!runId) {
    return (
      <div className="assistant-line">
        <div className="avatar assistant-avatar">A</div>
        <div className="message assistant-message history-answer">{message.content}</div>
      </div>
    );
  }

  return (
    <div className="assistant-line result-line">
      <div className="avatar assistant-avatar">A</div>
      <div className="agent-output historical-agent-output">
        <details
          className="trace-details"
          onToggle={(event) => setExpanded(event.currentTarget.open)}
        >
          <summary className="trace-header">
            <span><Network size={16} />Agent 执行过程 <ChevronDown className="trace-chevron" size={15} /></span>
            <small>历史记录</small>
          </summary>
          {eventsQuery.isLoading ? <div className="trace-loading">正在加载执行过程...</div> : null}
          {eventsQuery.error ? <div className="error-block">执行过程加载失败：{eventsQuery.error.message}</div> : null}
          {eventsQuery.data ? <RunTimeline events={eventsQuery.data} running={false} /> : null}
        </details>
        <div className="answer-block">
          <div className="answer-title"><CheckCircle2 size={17} />运行结果</div>
          <div className="answer-copy">{message.content}</div>
        </div>
      </div>
    </div>
  );
}
