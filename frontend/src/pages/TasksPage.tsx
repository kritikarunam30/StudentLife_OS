import { FormEvent, useState } from 'react';
import { api, type Task } from '../api/client';

type Props = { tasks: Task[]; onChanged: () => void };
const emptyForm = { title: '', deadline: '', priority: 'medium', category: '', estimated_effort_hours: '', description: '' };

export default function TasksPage({ tasks, onChanged }: Props) {
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);

  async function addTask(event: FormEvent) {
    event.preventDefault(); setError(null);
    try {
      const task = await api.createTask({ ...form, deadline: form.deadline ? new Date(form.deadline).toISOString() : null, category: form.category || null, description: form.description || null, estimated_effort_hours: form.estimated_effort_hours ? Number(form.estimated_effort_hours) : null, source: 'manual', status: 'pending', is_confirmed_deadline: true });
      await onChanged(); setForm(emptyForm);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Unable to create task.'); }
  }

  async function completeTask(task: Task) {
    try { await api.updateTask(task.id, { status: 'completed' }); await onChanged(); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Unable to update task.'); }
  }

  return <section className="tasks-page"><div className="section-heading"><div><p className="eyebrow">Deterministic task management</p><h2>Tasks</h2></div><span className="muted">{tasks.filter((task) => task.status !== 'completed').length} active</span></div>
    {error && <div className="notice error" role="alert">{error}</div>}
    <form className="task-form" onSubmit={addTask}><label className="wide">Task title<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="e.g. Finish operating systems notes" /></label><label>Deadline<input type="datetime-local" value={form.deadline} onChange={(event) => setForm({ ...form, deadline: event.target.value })} /></label><label>Priority<select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option></select></label><label>Category<input value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} placeholder="Academic, career..." /></label><label>Effort (hours)<input type="number" min="1" value={form.estimated_effort_hours} onChange={(event) => setForm({ ...form, estimated_effort_hours: event.target.value })} /></label><button className="primary-button" type="submit">Add task</button></form>
    <div className="task-list">{tasks.length ? tasks.map((task) => <article className={task.is_overdue ? 'task-row overdue' : 'task-row'} key={task.id}><div><strong>{task.title}</strong><p className="muted">{task.category || 'General'} · {task.priority} priority{task.deadline ? ` · due ${new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(task.deadline))}` : ' · no deadline'}</p></div>{task.status === 'completed' ? <span className="task-status">Completed</span> : <button className="secondary-button" onClick={() => completeTask(task)}>Complete</button>}</article>) : <p className="empty-state">Your task list is clear.</p>}</div>
  </section>;
}