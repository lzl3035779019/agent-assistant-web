import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, Clock3, ExternalLink, RefreshCw, RotateCcw, XCircle } from "lucide-react";

import { api } from "../api/client";
import type { AgentRun, RunStatus } from "../api/types";

interface Props {
  onOpenRun: (run: AgentRun) => void;
}

const statusOptions: Array<{ value: RunStatus | "all"; label: string }> = [
  { value: "all", label: "全部" },
  { value: "running", label: "运行中" },
  { value: "queued", label: "排队中" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
  { value: "completed", label: "已完成" },
];

function statusIcon(status: RunStatus) {
  if (status === "completed") return <CheckCircle2 size={16} />;
  if (status === "failed") return <XCircle size={16} />;
  if (status === "cancelled") return <Ban size={16} />;
  return <Clock3 size={16} />;
}

export function TaskCenterPage({ onOpenRun }: Props) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<RunStatus | "all">("all");
  const [page, setPage] = useState(0);
  const pageSize = 12;
  const query = useQuery({
    queryKey: ["runs", status, page],
    queryFn: () => api.listRuns({
      status: status === "all" ? undefined : status,
      limit: pageSize,
      offset: page * pageSize,
    }),
    refetchInterval: (state) => state.state.data?.items.some((run) => run.status === "queued" || run.status === "running") ? 2000 : false,
  });
  const cancelMutation = useMutation({
    mutationFn: api.cancelRun,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });
  const retryMutation = useMutation({
    mutationFn: api.retryRun,
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      onOpenRun(run);
    },
  });

  return (
    <main className="task-center-workspace">
      <header className="module-header task-center-header">
        <div><span className="eyebrow">RUN CONTROL</span><h1>任务与失败中心</h1><p>查看后台任务、定位错误，并执行取消或重试。</p></div>
        <button className="icon-action" onClick={() => query.refetch()} title="刷新任务" type="button"><RefreshCw size={17} /></button>
      </header>
      <section className="task-center-content">
        <div className="run-filter" role="tablist">
          {statusOptions.map((option) => <button className={status === option.value ? "active" : ""} key={option.value} onClick={() => { setStatus(option.value); setPage(0); }} type="button">{option.label}</button>)}
        </div>
        {query.isLoading ? <div className="module-empty">正在读取任务记录...</div> : null}
        {query.error ? <div className="inline-error">{query.error.message}</div> : null}
        <div className="run-card-grid">
          {query.data?.items.map((run) => (
            <article className={`run-card status-${run.status}`} key={run.id}>
              <header><span className="run-status-icon">{statusIcon(run.status)}</span><div><strong>{run.objective}</strong><small>{run.run_type} · {new Date(run.created_at).toLocaleString()}</small></div><em>{run.status}</em></header>
              <dl>
                <div><dt>Run ID</dt><dd>{run.id.slice(0, 12)}</dd></div>
                <div><dt>执行时长</dt><dd>{run.started_at && run.finished_at ? `${Math.max(0, Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000))}s` : "-"}</dd></div>
                <div><dt>执行次数</dt><dd>{run.attempt_count} / {run.max_attempts}</dd></div>
                {run.retry_of_run_id ? <div><dt>重试来源</dt><dd>{run.retry_of_run_id.slice(0, 12)}</dd></div> : null}
              </dl>
              {run.error ? <p className="run-card-error">{run.error}</p> : null}
              <footer>
                <button onClick={() => onOpenRun(run)} type="button"><ExternalLink size={14} />查看执行</button>
                {run.status === "queued" || run.status === "running" ? <button className="danger" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate(run.id)} type="button"><Ban size={14} />取消</button> : null}
                {run.status === "failed" || run.status === "cancelled" ? <button disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(run.id)} type="button"><RotateCcw size={14} />重试</button> : null}
              </footer>
            </article>
          ))}
        </div>
        {!query.isLoading && !query.data?.items.length ? <div className="module-empty">当前筛选条件下没有任务。</div> : null}
        {(query.data?.total ?? 0) > pageSize ? <div className="task-pagination"><button disabled={page === 0} onClick={() => setPage((value) => value - 1)} type="button">上一页</button><span>{page + 1} / {Math.ceil((query.data?.total ?? 0) / pageSize)}</span><button disabled={(page + 1) * pageSize >= (query.data?.total ?? 0)} onClick={() => setPage((value) => value + 1)} type="button">下一页</button></div> : null}
      </section>
    </main>
  );
}
