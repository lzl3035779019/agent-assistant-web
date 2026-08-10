import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  Check,
  CheckSquare2,
  CircleAlert,
  Clock3,
  Edit3,
  ListTodo,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import { api } from "../api/client";
import type { CalendarAction, CalendarEvent, TodoItem } from "../api/types";

const todayInShanghai = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(new Date());

function addDays(date: string, amount: number) {
  const value = new Date(`${date}T00:00:00+08:00`);
  value.setUTCDate(value.getUTCDate() + amount);
  return value.toISOString();
}

function localIso(date: string, time: string) {
  return `${date}T${time}:00+08:00`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function dateInput(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function timeInput(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function actionTitle(action: CalendarAction) {
  return {
    "event.create": "新建日程",
    "event.update": "修改日程",
    "event.cancel": "取消日程",
    "todo.create": "新建待办",
    "todo.update": "修改待办",
    "todo.cancel": "取消待办",
  }[action.action];
}

interface EventForm {
  id: string;
  title: string;
  date: string;
  start: string;
  end: string;
  location: string;
  description: string;
}

interface TodoForm {
  id: string;
  title: string;
  dueDate: string;
  dueTime: string;
  priority: number;
  description: string;
}

const emptyEvent = (): EventForm => ({
  id: "",
  title: "",
  date: todayInShanghai(),
  start: "09:00",
  end: "10:00",
  location: "",
  description: "",
});

const emptyTodo = (): TodoForm => ({
  id: "",
  title: "",
  dueDate: "",
  dueTime: "18:00",
  priority: 5,
  description: "",
});

export function CalendarPage() {
  const queryClient = useQueryClient();
  const [rangeStart, setRangeStart] = useState(todayInShanghai());
  const [rangeDays, setRangeDays] = useState(30);
  const [eventForm, setEventForm] = useState<EventForm | null>(null);
  const [todoForm, setTodoForm] = useState<TodoForm | null>(null);
  const [pendingAction, setPendingAction] = useState<CalendarAction | null>(null);

  const range = useMemo(() => ({
    startAt: localIso(rangeStart, "00:00"),
    endAt: addDays(rangeStart, rangeDays),
  }), [rangeDays, rangeStart]);

  const statsQuery = useQuery({ queryKey: ["calendar-stats"], queryFn: api.getCalendarStats });
  const eventsQuery = useQuery({
    queryKey: ["calendar-events", range],
    queryFn: () => api.listCalendarEvents(range),
  });
  const todosQuery = useQuery({ queryKey: ["calendar-todos"], queryFn: () => api.listTodos(false) });

  const prepare = useMutation({
    mutationFn: api.prepareCalendarAction,
    onSuccess: setPendingAction,
  });
  const confirm = useMutation({
    mutationFn: api.confirmCalendarAction,
    onSuccess() {
      setPendingAction(null);
      setEventForm(null);
      setTodoForm(null);
      refreshAll();
    },
  });
  const cancel = useMutation({
    mutationFn: api.cancelCalendarAction,
    onSuccess: () => setPendingAction(null),
  });

  function refreshAll() {
    void queryClient.invalidateQueries({ queryKey: ["calendar-stats"] });
    void queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
    void queryClient.invalidateQueries({ queryKey: ["calendar-todos"] });
  }

  function editEvent(event: CalendarEvent) {
    setTodoForm(null);
    setEventForm({
      id: event.id,
      title: event.title,
      date: dateInput(event.start_at),
      start: timeInput(event.start_at),
      end: timeInput(event.end_at),
      location: event.location,
      description: event.description,
    });
  }

  function editTodo(todo: TodoItem) {
    setEventForm(null);
    setTodoForm({
      id: todo.id,
      title: todo.title,
      dueDate: todo.due_at ? dateInput(todo.due_at) : "",
      dueTime: todo.due_at ? timeInput(todo.due_at) : "18:00",
      priority: todo.priority,
      description: todo.description,
    });
  }

  function submitEvent(event: FormEvent) {
    event.preventDefault();
    if (!eventForm?.title.trim()) return;
    prepare.mutate({
      action: eventForm.id ? "event.update" : "event.create",
      target_id: eventForm.id || undefined,
      payload: {
        title: eventForm.title,
        description: eventForm.description,
        location: eventForm.location,
        start_at: localIso(eventForm.date, eventForm.start),
        end_at: localIso(eventForm.date, eventForm.end),
      },
    });
  }

  function submitTodo(event: FormEvent) {
    event.preventDefault();
    if (!todoForm?.title.trim()) return;
    prepare.mutate({
      action: todoForm.id ? "todo.update" : "todo.create",
      target_id: todoForm.id || undefined,
      payload: {
        title: todoForm.title,
        description: todoForm.description,
        due_at: todoForm.dueDate ? localIso(todoForm.dueDate, todoForm.dueTime) : null,
        priority: todoForm.priority,
      },
    });
  }

  return (
    <main className="calendar-workspace">
      <header className="module-header">
        <div>
          <span className="eyebrow">CALENDAR / TASK AGENT</span>
          <h1>日历与任务</h1>
          <p>查看未来日程、管理待办、检测时间冲突；所有写操作都需要用户确认。</p>
        </div>
        <div className="calendar-header-actions">
          <button onClick={() => { setTodoForm(null); setEventForm(emptyEvent()); }} type="button"><CalendarClock size={15} />新建日程</button>
          <button onClick={() => { setEventForm(null); setTodoForm(emptyTodo()); }} type="button"><ListTodo size={15} />新建待办</button>
        </div>
      </header>

      <div className="calendar-content">
        <section className="calendar-overview">
          <div><CalendarClock size={17} /><span>今日日程</span><strong>{statsQuery.data?.today_events ?? 0}</strong></div>
          <div><Clock3 size={17} /><span>未来日程</span><strong>{statsQuery.data?.upcoming_events ?? 0}</strong></div>
          <div><CheckSquare2 size={17} /><span>未完成待办</span><strong>{statsQuery.data?.open_todos ?? 0}</strong></div>
          <div className={statsQuery.data?.overdue_todos ? "attention" : ""}><CircleAlert size={17} /><span>已逾期</span><strong>{statsQuery.data?.overdue_todos ?? 0}</strong></div>
        </section>

        <section className="calendar-range-bar">
          <label>开始日期<input onChange={(event) => setRangeStart(event.target.value)} type="date" value={rangeStart} /></label>
          <label>查看范围<select onChange={(event) => setRangeDays(Number(event.target.value))} value={rangeDays}><option value={7}>未来 7 天</option><option value={30}>未来 30 天</option><option value={90}>未来 90 天</option></select></label>
          <button onClick={refreshAll} title="刷新日程和待办" type="button"><RefreshCw size={15} />刷新</button>
        </section>

        {eventForm ? (
          <form className="calendar-editor" onSubmit={submitEvent}>
            <div className="calendar-editor-heading"><strong>{eventForm.id ? "修改日程" : "新建日程"}</strong><button onClick={() => setEventForm(null)} title="关闭" type="button"><X size={16} /></button></div>
            <label className="wide">标题<input onChange={(event) => setEventForm({ ...eventForm, title: event.target.value })} required value={eventForm.title} /></label>
            <label>日期<input onChange={(event) => setEventForm({ ...eventForm, date: event.target.value })} required type="date" value={eventForm.date} /></label>
            <label>开始<input onChange={(event) => setEventForm({ ...eventForm, start: event.target.value })} required type="time" value={eventForm.start} /></label>
            <label>结束<input onChange={(event) => setEventForm({ ...eventForm, end: event.target.value })} required type="time" value={eventForm.end} /></label>
            <label className="wide">地点<input onChange={(event) => setEventForm({ ...eventForm, location: event.target.value })} value={eventForm.location} /></label>
            <label className="wide">备注<textarea onChange={(event) => setEventForm({ ...eventForm, description: event.target.value })} rows={3} value={eventForm.description} /></label>
            <button className="module-primary-button wide" disabled={prepare.isPending} type="submit"><ShieldCheck size={15} />提交并检查冲突</button>
          </form>
        ) : null}

        {todoForm ? (
          <form className="calendar-editor todo-editor" onSubmit={submitTodo}>
            <div className="calendar-editor-heading"><strong>{todoForm.id ? "修改待办" : "新建待办"}</strong><button onClick={() => setTodoForm(null)} title="关闭" type="button"><X size={16} /></button></div>
            <label className="wide">标题<input onChange={(event) => setTodoForm({ ...todoForm, title: event.target.value })} required value={todoForm.title} /></label>
            <label>截止日期<input onChange={(event) => setTodoForm({ ...todoForm, dueDate: event.target.value })} type="date" value={todoForm.dueDate} /></label>
            <label>截止时间<input disabled={!todoForm.dueDate} onChange={(event) => setTodoForm({ ...todoForm, dueTime: event.target.value })} type="time" value={todoForm.dueTime} /></label>
            <label>优先级<select onChange={(event) => setTodoForm({ ...todoForm, priority: Number(event.target.value) })} value={todoForm.priority}><option value={3}>低</option><option value={5}>普通</option><option value={8}>高</option><option value={10}>紧急</option></select></label>
            <label className="wide">说明<textarea onChange={(event) => setTodoForm({ ...todoForm, description: event.target.value })} rows={3} value={todoForm.description} /></label>
            <button className="module-primary-button wide" disabled={prepare.isPending} type="submit"><ShieldCheck size={15} />提交待办操作</button>
          </form>
        ) : null}

        {prepare.error ? <div className="inline-error">{prepare.error.message}</div> : null}

        <div className="calendar-board">
          <section className="calendar-column">
            <div className="calendar-column-title"><div><CalendarClock size={17} /><strong>日程</strong></div><span>{eventsQuery.data?.length ?? 0}</span></div>
            {eventsQuery.isLoading ? <div className="module-empty">正在加载日程...</div> : null}
            {eventsQuery.error ? <div className="inline-error">{eventsQuery.error.message}</div> : null}
            <div className="calendar-card-grid">
              {eventsQuery.data?.map((event) => (
                <article className="schedule-card" key={event.id}>
                  <div className="schedule-card-top"><CalendarClock size={15} /><strong>{event.title}</strong></div>
                  <time>{formatTime(event.start_at)} - {timeInput(event.end_at)}</time>
                  <p>{event.location || "未设置地点"}</p>
                  {event.description ? <small>{event.description}</small> : null}
                  <div className="schedule-card-actions">
                    <button onClick={() => editEvent(event)} type="button"><Edit3 size={13} />修改</button>
                    <button className="danger" onClick={() => prepare.mutate({ action: "event.cancel", target_id: event.id, payload: { title: event.title } })} type="button"><Trash2 size={13} />取消</button>
                  </div>
                </article>
              ))}
            </div>
            {!eventsQuery.isLoading && !eventsQuery.data?.length ? <div className="module-empty">所选范围内没有日程。</div> : null}
          </section>

          <section className="calendar-column">
            <div className="calendar-column-title"><div><ListTodo size={17} /><strong>待办事项</strong></div><span>{todosQuery.data?.length ?? 0}</span></div>
            {todosQuery.isLoading ? <div className="module-empty">正在加载待办...</div> : null}
            {todosQuery.error ? <div className="inline-error">{todosQuery.error.message}</div> : null}
            <div className="todo-list">
              {todosQuery.data?.map((todo) => (
                <article className={`todo-card priority-${todo.priority}`} key={todo.id}>
                  <button className="todo-complete" onClick={() => prepare.mutate({ action: "todo.update", target_id: todo.id, payload: { status: "completed", title: todo.title } })} title="标记完成" type="button"><Check size={14} /></button>
                  <div><strong>{todo.title}</strong><span>{todo.due_at ? `截止 ${formatTime(todo.due_at)}` : "无截止时间"}</span>{todo.description ? <p>{todo.description}</p> : null}</div>
                  <div className="todo-actions"><button onClick={() => editTodo(todo)} title="修改" type="button"><Edit3 size={13} /></button><button className="danger" onClick={() => prepare.mutate({ action: "todo.cancel", target_id: todo.id, payload: { title: todo.title } })} title="取消" type="button"><Trash2 size={13} /></button></div>
                </article>
              ))}
            </div>
            {!todosQuery.isLoading && !todosQuery.data?.length ? <div className="module-empty">暂无未完成待办。</div> : null}
          </section>
        </div>
      </div>

      {pendingAction ? (
        <div className="action-modal-backdrop" role="presentation">
          <section aria-modal="true" className="action-modal" role="dialog">
            <div className="action-modal-heading"><div><ShieldCheck size={18} /><strong>确认操作</strong></div><button onClick={() => cancel.mutate(pendingAction.id)} title="关闭并取消操作" type="button"><X size={17} /></button></div>
            <span className="action-kind">{actionTitle(pendingAction)}</span>
            <dl className="action-preview">
              {Object.entries(pendingAction.payload).filter(([key]) => key !== "description").map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? "未设置")}</dd></div>)}
            </dl>
            {pendingAction.result_payload.has_conflict ? (
              <div className="conflict-warning"><CircleAlert size={17} /><div><strong>检测到时间冲突</strong>{pendingAction.result_payload.conflicts?.map((item) => <span key={item.id}>{item.title} · {formatTime(item.start_at)} - {timeInput(item.end_at)}</span>)}</div></div>
            ) : <div className="no-conflict"><Check size={15} />未检测到时间冲突</div>}
            <p>确认后才会写入系统；取消不会修改任何日程或待办。</p>
            <div className="action-modal-buttons"><button className="confirm" disabled={confirm.isPending} onClick={() => confirm.mutate(pendingAction.id)} type="button">确认执行</button><button disabled={cancel.isPending} onClick={() => cancel.mutate(pendingAction.id)} type="button">取消</button></div>
            {confirm.error ? <div className="inline-error">{confirm.error.message}</div> : null}
          </section>
        </div>
      ) : null}
    </main>
  );
}
