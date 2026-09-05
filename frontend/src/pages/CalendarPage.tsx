import { FormEvent, useState } from 'react';
import { api, type CalendarEvent } from '../api/client';

type Props = { events: CalendarEvent[]; onChanged: () => void };
const emptyForm = { title: '', starts_at: '', ends_at: '', event_type: 'event', location: '' };

function toPayload(form: typeof emptyForm) {
  return { title: form.title, description: null, starts_at: new Date(form.starts_at).toISOString(), ends_at: new Date(form.ends_at).toISOString(), event_type: form.event_type, location: form.location || null, task_id: null };
}

export default function CalendarPage({ events, onChanged }: Props) {
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);

  async function addEvent(event: FormEvent) {
    event.preventDefault(); setError(null);
    try {
      const payload = toPayload(form);
      const conflict = await api.checkCalendarConflicts(payload);
      if (conflict.has_conflict) { setError(conflict.reasons.join('; ')); return; }
      await api.createCalendarEvent(payload); await onChanged(); setForm(emptyForm);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Unable to schedule event.'); }
  }

  return <section className="calendar-page"><div className="section-heading"><div><p className="eyebrow">Deterministic scheduling</p><h2>Calendar</h2></div><span className="muted">{events.length} scheduled</span></div>
    {error && <div className="notice error" role="alert">{error}</div>}
    <form className="task-form calendar-form" onSubmit={addEvent}><label className="wide">Event title<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="e.g. Algorithms lecture" /></label><label>Starts<input required type="datetime-local" value={form.starts_at} onChange={(event) => setForm({ ...form, starts_at: event.target.value })} /></label><label>Ends<input required type="datetime-local" value={form.ends_at} onChange={(event) => setForm({ ...form, ends_at: event.target.value })} /></label><label>Type<select value={form.event_type} onChange={(event) => setForm({ ...form, event_type: event.target.value })}><option value="event">Event</option><option value="class">Class</option><option value="study">Study</option></select></label><label>Location<input value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label><button className="primary-button" type="submit">Schedule</button></form>
    <div className="event-list">{events.length ? events.map((item) => <article className="event-row" key={item.id}><div><strong>{item.title}</strong><p className="muted">{item.event_type}{item.location ? ` · ${item.location}` : ''}</p></div><time>{new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(item.starts_at))} - {new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(item.ends_at))}</time></article>) : <p className="empty-state">No events scheduled yet.</p>}</div>
  </section>;
}