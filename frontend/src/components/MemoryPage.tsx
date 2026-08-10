import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CircleUserRound,
  Edit3,
  FolderKanban,
  Heart,
  MemoryStick,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import { api } from "../api/client";
import type { MemoryType, UserMemory } from "../api/types";

const typeCopy: Record<MemoryType, { label: string; icon: typeof Heart }> = {
  profile: { label: "用户资料", icon: CircleUserRound },
  preference: { label: "偏好", icon: Heart },
  project: { label: "项目事实", icon: FolderKanban },
  instruction: { label: "长期指令", icon: ShieldCheck },
};

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function MemoryPage() {
  const queryClient = useQueryClient();
  const [memoryType, setMemoryType] = useState<MemoryType | "">("");
  const [status, setStatus] = useState<"" | "enabled" | "disabled">("");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newType, setNewType] = useState<MemoryType>("preference");
  const [newContent, setNewContent] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState("");

  const filters = {
    memoryType: memoryType || undefined,
    enabled: status ? status === "enabled" : undefined,
    query: search.trim() || undefined,
  };
  const memoriesQuery = useQuery({
    queryKey: ["memories", filters],
    queryFn: () => api.listMemories(filters),
  });
  const statsQuery = useQuery({ queryKey: ["memory-stats"], queryFn: api.getMemoryStats });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["memories"] });
    void queryClient.invalidateQueries({ queryKey: ["memory-stats"] });
  }

  const createMemory = useMutation({
    mutationFn: api.createMemory,
    onSuccess() {
      setNewContent("");
      setShowCreate(false);
      refresh();
    },
  });
  const updateMemory = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof api.updateMemory>[1] }) =>
      api.updateMemory(id, payload),
    onSuccess() {
      setEditingId(null);
      refresh();
    },
  });
  const deleteMemory = useMutation({ mutationFn: api.deleteMemory, onSuccess: refresh });

  function submitNew(event: FormEvent) {
    event.preventDefault();
    const content = newContent.trim();
    if (content) createMemory.mutate({ memory_type: newType, content });
  }

  function beginEdit(memory: UserMemory) {
    setEditingId(memory.id);
    setEditingContent(memory.content);
  }

  const stats = statsQuery.data;
  const memories = memoriesQuery.data ?? [];

  return (
    <main className="memory-workspace">
      <header className="module-header">
        <div>
          <span className="eyebrow">MEMORY AGENT</span>
          <h1>长期记忆</h1>
          <p>检索、提取、验证并维护用户画像、偏好、长期指令和项目事实。</p>
        </div>
        <button className="module-primary-button" onClick={() => setShowCreate(true)} type="button">
          <Plus size={16} />新增记忆
        </button>
      </header>

      <div className="memory-content">
        <section className="memory-overview" aria-label="记忆概览">
          <div><MemoryStick size={18} /><span>全部记忆</span><strong>{stats?.total ?? 0}</strong></div>
          <div><Check size={18} /><span>已启用</span><strong>{stats?.enabled ?? 0}</strong></div>
          <div><X size={18} /><span>已禁用</span><strong>{stats?.disabled ?? 0}</strong></div>
          <div><Heart size={18} /><span>偏好</span><strong>{stats?.by_type.preference ?? 0}</strong></div>
        </section>

        {showCreate ? (
          <form className="memory-create" onSubmit={submitNew}>
            <div className="memory-create-heading"><strong>新增长期记忆</strong><button onClick={() => setShowCreate(false)} title="关闭" type="button"><X size={16} /></button></div>
            <select onChange={(event) => setNewType(event.target.value as MemoryType)} value={newType}>
              {Object.entries(typeCopy).map(([value, copy]) => <option key={value} value={value}>{copy.label}</option>)}
            </select>
            <textarea onChange={(event) => setNewContent(event.target.value)} placeholder="输入明确且长期有效的信息" rows={3} value={newContent} />
            <button className="module-primary-button" disabled={!newContent.trim() || createMemory.isPending} type="submit">保存记忆</button>
            {createMemory.error ? <span className="inline-error">{createMemory.error.message}</span> : null}
          </form>
        ) : null}

        <section className="memory-toolbar">
          <label className="memory-search"><Search size={15} /><input onChange={(event) => setSearch(event.target.value)} placeholder="搜索记忆内容" value={search} /></label>
          <select onChange={(event) => setMemoryType(event.target.value as MemoryType | "")} value={memoryType}>
            <option value="">全部类型</option>
            {Object.entries(typeCopy).map(([value, copy]) => <option key={value} value={value}>{copy.label}</option>)}
          </select>
          <select onChange={(event) => setStatus(event.target.value as typeof status)} value={status}>
            <option value="">全部状态</option>
            <option value="enabled">已启用</option>
            <option value="disabled">已禁用</option>
          </select>
        </section>

        <section className="memory-list">
          {memoriesQuery.isLoading ? <div className="module-empty">正在读取长期记忆...</div> : null}
          {!memoriesQuery.isLoading && !memories.length ? <div className="module-empty">当前筛选条件下没有长期记忆。</div> : null}
          {memories.map((memory) => {
            const copy = typeCopy[memory.memory_type];
            const Icon = copy.icon;
            const editing = editingId === memory.id;
            return (
              <article className={`memory-row${memory.enabled ? "" : " disabled"}`} key={memory.id}>
                <div className="memory-type-icon"><Icon size={17} /></div>
                <div className="memory-main">
                  <div className="memory-row-meta"><span>{copy.label}</span><small>置信度 {Math.round(memory.confidence * 100)}%</small></div>
                  {editing ? (
                    <textarea onChange={(event) => setEditingContent(event.target.value)} rows={3} value={editingContent} />
                  ) : <p>{memory.content}</p>}
                  <div className="memory-row-foot">
                    <span>{memory.source === "manual" ? "手动添加" : "Memory Agent 提取"}</span>
                    <span>使用 {memory.usage_count} 次</span>
                    <span>更新于 {formatTime(memory.updated_at)}</span>
                  </div>
                </div>
                <div className="memory-actions">
                  {editing ? (
                    <>
                      <button onClick={() => updateMemory.mutate({ id: memory.id, payload: { content: editingContent.trim() } })} title="保存修改" type="button"><Check size={15} /></button>
                      <button onClick={() => setEditingId(null)} title="取消修改" type="button"><X size={15} /></button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => beginEdit(memory)} title="编辑" type="button"><Edit3 size={15} /></button>
                      <button onClick={() => updateMemory.mutate({ id: memory.id, payload: { enabled: !memory.enabled } })} title={memory.enabled ? "禁用" : "启用"} type="button">{memory.enabled ? <X size={15} /> : <Check size={15} />}</button>
                      <button className="danger" onClick={() => window.confirm("确定删除这条长期记忆吗？") && deleteMemory.mutate(memory.id)} title="删除" type="button"><Trash2 size={15} /></button>
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </section>
      </div>
    </main>
  );
}
