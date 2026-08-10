import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Database,
  FileText,
  LoaderCircle,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";

import { api } from "../api/client";
import type { KnowledgeDocument } from "../api/types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function statusCopy(document: KnowledgeDocument) {
  if (document.status === "indexed") return "可检索";
  if (document.status === "failed") return "处理失败";
  if (document.status === "processing") return "正在解析";
  return "等待处理";
}

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const documents = useQuery({
    queryKey: ["knowledge-documents"],
    queryFn: api.listDocuments,
    refetchInterval: (query) =>
      query.state.data?.some((item) => ["queued", "processing"].includes(item.status))
        ? 1200
        : false,
  });
  const stats = useQuery({
    queryKey: ["knowledge-stats"],
    queryFn: api.getKnowledgeStats,
    refetchInterval: documents.data?.some((item) => ["queued", "processing"].includes(item.status))
      ? 1200
      : false,
  });
  const upload = useMutation({
    mutationFn: api.uploadDocument,
    async onSuccess() {
      setSelectedFile(null);
      if (inputRef.current) inputRef.current.value = "";
      await queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
      await queryClient.invalidateQueries({ queryKey: ["knowledge-stats"] });
    },
  });
  const remove = useMutation({
    mutationFn: api.deleteDocument,
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
      await queryClient.invalidateQueries({ queryKey: ["knowledge-stats"] });
    },
  });

  const processing = useMemo(
    () => documents.data?.filter((item) => ["queued", "processing"].includes(item.status)).length ?? 0,
    [documents.data],
  );

  return (
    <main className="knowledge-workspace">
      <div className="knowledge-header">
        <div><span className="eyebrow">AGENTIC RAG KNOWLEDGE BASE</span><h1>知识库工作台</h1></div>
        <div className="knowledge-header-meta"><Database size={16} />PostgreSQL · Qdrant · MinIO</div>
      </div>

      <div className="knowledge-content">
        <section className="upload-panel">
          <div className="section-heading"><div><h2>导入资料</h2><p>文件将由后台任务解析、切分和建立检索索引。</p></div></div>
          <button className="upload-dropzone" onClick={() => inputRef.current?.click()} type="button">
            <Upload size={25} />
            <strong>{selectedFile ? selectedFile.name : "选择需要入库的文件"}</strong>
            <span>支持 PDF、DOCX、Markdown、TXT，单文件不超过 50 MB</span>
          </button>
          <input
            accept=".pdf,.docx,.md,.markdown,.txt"
            hidden
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            ref={inputRef}
            type="file"
          />
          <button
            className="primary-action"
            disabled={!selectedFile || upload.isPending}
            onClick={() => selectedFile && upload.mutate(selectedFile)}
            type="button"
          >
            {upload.isPending ? <LoaderCircle className="spin" size={17} /> : <Upload size={17} />}
            {upload.isPending ? "正在上传" : "上传并建立索引"}
          </button>
          {upload.error ? <div className="inline-error">{upload.error.message}</div> : null}
        </section>

        <section className="knowledge-library">
          <div className="stats-row">
            <div><span>文档</span><strong>{stats.data?.document_count ?? 0}</strong></div>
            <div><span>已索引</span><strong>{stats.data?.indexed_count ?? 0}</strong></div>
            <div><span>文本块</span><strong>{stats.data?.chunk_count ?? 0}</strong></div>
            <div><span>处理中</span><strong>{processing}</strong></div>
          </div>

          <div className="section-heading document-heading">
            <div><h2>知识文档</h2><p>只有状态为“可检索”的文档会参与回答。</p></div>
          </div>
          {documents.isLoading ? <div className="library-empty"><LoaderCircle className="spin" />读取文档列表</div> : null}
          {!documents.isLoading && !documents.data?.length ? (
            <div className="library-empty"><FileText />尚未上传资料</div>
          ) : null}
          <div className="document-list">
            {documents.data?.map((document) => (
              <article className="document-row" key={document.id}>
                <div className={`document-icon status-${document.status}`}>
                  {document.status === "indexed" ? <CheckCircle2 size={18} /> : document.status === "failed" ? <XCircle size={18} /> : <LoaderCircle className="spin" size={18} />}
                </div>
                <div className="document-copy">
                  <strong>{document.filename}</strong>
                  <span>{formatBytes(document.size_bytes)} · {document.chunk_count} 个文本块 · {statusCopy(document)}</span>
                  {document.error ? <small>{document.error}</small> : null}
                </div>
                <button
                  className="icon-action danger"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(document.id)}
                  title="删除文档"
                  type="button"
                ><Trash2 size={17} /></button>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
