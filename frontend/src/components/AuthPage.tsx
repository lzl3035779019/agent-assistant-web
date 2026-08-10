import { type FormEvent, useState } from "react";
import { ArrowRight, LockKeyhole, Network, UserRoundPlus } from "lucide-react";

import { api, saveAuthTokens } from "../api/client";

interface Props {
  onAuthenticated: () => void;
}

export function AuthPage({ onAuthenticated }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const payload = { email: email.trim(), password, display_name: displayName.trim() || undefined };
      const tokens = mode === "login" ? await api.login(payload) : await api.register(payload);
      saveAuthTokens(tokens);
      onAuthenticated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "认证失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-intro">
        <span className="auth-kicker"><Network size={15} /> PERSONAL MULTI-AGENT ASSISTANT</span>
        <h1>一个账号，一套隔离的 Agent 工作空间</h1>
        <p>对话、长期记忆、知识文档、邮件动作和后台任务均按用户隔离。</p>
        <div className="auth-capabilities">
          <span>Supervisor DAG</span><span>Agentic RAG</span><span>Human-in-the-loop</span>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-tabs" role="tablist">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")} type="button">登录</button>
          <button className={mode === "register" ? "active" : ""} onClick={() => setMode("register")} type="button">注册</button>
        </div>
        <div className="auth-heading">
          {mode === "login" ? <LockKeyhole size={20} /> : <UserRoundPlus size={20} />}
          <div><h2>{mode === "login" ? "返回工作空间" : "创建个人工作空间"}</h2><p>JWT 访问令牌与可轮换刷新令牌</p></div>
        </div>
        <form onSubmit={submit}>
          {mode === "register" ? <label>显示名称<input autoComplete="name" onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：小林" value={displayName} /></label> : null}
          <label>邮箱<input autoComplete="email" onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" required type="email" value={email} /></label>
          <label>密码<input autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={8} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></label>
          {error ? <div className="auth-error">{error}</div> : null}
          <button className="auth-submit" disabled={submitting} type="submit">
            {submitting ? "正在验证..." : mode === "login" ? "进入工作空间" : "创建账号"}<ArrowRight size={17} />
          </button>
        </form>
      </section>
    </main>
  );
}
