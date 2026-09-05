import { useEffect, useState } from 'react';
import { api, type Approval, type Assignment, type CalendarEvent, type Exam, type ProfileResponse, type StudyPlan, type Task } from './api/client';
import Onboarding from './pages/Onboarding';
import TasksPage from './pages/TasksPage';
import CalendarPage from './pages/CalendarPage';
import InboxModal from './components/InboxModal';
import BriefingModal from './components/BriefingModal';
import ApprovalsPage from './pages/ApprovalsPage';
import AcademicPage from './pages/AcademicPage';
import OpportunitiesPage from './pages/OpportunitiesPage';
import DSAPage from './pages/DSAPage';

type View = 'dashboard' | 'tasks' | 'calendar' | 'academic' | 'opportunities' | 'dsa' | 'approvals' | 'settings';
type WorkspaceData = { profile: ProfileResponse; tasks: Task[]; calendar: CalendarEvent[]; approvals: Approval[]; assignments: Assignment[]; exams: Exam[]; studyPlans: StudyPlan[] };

function formatDate(value: string | null) {
  if (!value) return 'No deadline';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value));
}

function EmptyState({ message }: { message: string }) { return <p className="empty-state">{message}</p>; }

export default function App() {
  const [view, setView] = useState<View>('dashboard');
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isInboxOpen, setIsInboxOpen] = useState(false);
  const [isBriefingOpen, setIsBriefingOpen] = useState(false);

  const refreshData = () => {
    Promise.all([api.getProfile(), api.getTasks(), api.getCalendar(), api.getApprovals(), api.getAssignments(), api.getExams(), api.getStudyPlans()])
      .then(([profile, tasks, calendar, approvals, assignments, exams, studyPlans]) => setData({ profile, tasks, calendar, approvals, assignments, exams, studyPlans }))
      .catch((requestError: unknown) => setError(requestError instanceof Error ? requestError.message : 'Unable to connect to the backend.'));
  };

  useEffect(() => {
    refreshData();
  }, []);

  const profileName = data?.profile.user.full_name;
  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="brand-mark">SL</div><div className="brand-copy"><strong>Student Life</strong><span>OS / local workspace</span></div>
        <nav aria-label="Primary navigation"><button className={view === 'dashboard' ? 'nav-link active' : 'nav-link'} onClick={() => setView('dashboard')}>Dashboard</button><button className={view === 'tasks' ? 'nav-link active' : 'nav-link'} onClick={() => setView('tasks')}>Tasks</button><button className={view === 'calendar' ? 'nav-link active' : 'nav-link'} onClick={() => setView('calendar')}>Calendar</button><button className={view === 'academic' ? 'nav-link active' : 'nav-link'} onClick={() => setView('academic')}>Academic</button><button className={view === 'opportunities' ? 'nav-link active' : 'nav-link'} onClick={() => setView('opportunities')}>Career</button><button className={view === 'dsa' ? 'nav-link active' : 'nav-link'} onClick={() => setView('dsa')}>DSA</button><button className={view === 'approvals' ? 'nav-link active' : 'nav-link'} onClick={() => setView('approvals')}>Approvals</button><button className={view === 'settings' ? 'nav-link active' : 'nav-link'} onClick={() => setView('settings')}>Settings</button></nav>
        <div className="sidebar-footer"><span className="status-dot" /> Local mode</div>
      </aside>
      <main className="app-shell">
        <header className="topbar"><div><p className="eyebrow">{view === 'dashboard' ? 'Workspace overview' : view === 'calendar' ? 'Schedule' : 'Student workspace'}</p><h1>{view === 'dashboard' ? (profileName ? `Good morning, ${profileName}` : 'Workspace overview') : view[0].toUpperCase() + view.slice(1)}</h1></div><div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}><button className="btn btn-secondary" onClick={() => setIsBriefingOpen(true)}>Morning Briefing</button><button className="btn btn-secondary" onClick={() => setIsInboxOpen(true)}>AI Extractor</button><div className="date-chip">{new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}</div></div></header>
        {error && <div className="notice error" role="alert">Backend unavailable. Start FastAPI to load your local workspace.</div>}
        {!data && !error && <div className="notice">Connecting to your local workspace...</div>}
        {data?.profile.profile === null && <Onboarding profile={data.profile} onSaved={(profile) => setData({ ...data, profile })} />}
        {data && data.profile.profile !== null && view === 'tasks' && <TasksPage tasks={data.tasks} onChanged={refreshData} />}
        {data && data.profile.profile !== null && view === 'calendar' && <CalendarPage events={data.calendar} onChanged={refreshData} />}
        {data && data.profile.profile !== null && view === 'academic' && <AcademicPage assignments={data.assignments} exams={data.exams} studyPlans={data.studyPlans} />}
        {data && data.profile.profile !== null && view === 'opportunities' && <OpportunitiesPage />}
        {data && data.profile.profile !== null && view === 'dsa' && <DSAPage />}
        {data && data.profile.profile !== null && view === 'approvals' && <ApprovalsPage approvals={data.approvals} onChanged={refreshData} />}
        {data?.profile.profile !== null && view === 'dashboard' && <section className="dashboard-content"><div className="section-heading"><div><p className="eyebrow">At a glance</p><h2>Today&apos;s rhythm</h2></div><span className="muted">{data?.tasks.length ?? 0} active tasks</span></div><section className="grid">
          <div className="card feature-card"><div className="card-heading"><h2>Tasks</h2><span className="number">{data?.tasks.length ?? 0}</span></div>{data?.tasks.length ? <ul>{data.tasks.slice(0, 4).map((task) => <li key={task.id}><span>{task.title}</span><time>{formatDate(task.deadline)}</time></li>)}</ul> : <EmptyState message="Your task list is clear." />}</div>
          <div className="card"><div className="card-heading"><h2>Next on the calendar</h2><span className="number">{data?.calendar.length ?? 0}</span></div>{data?.calendar.length ? <ul>{data.calendar.slice(0, 3).map((event) => <li key={event.id}><span>{event.title}</span><time>{formatDate(event.starts_at)}</time></li>)}</ul> : <EmptyState message="No events scheduled yet." />}</div>
          <div className="card"><div className="card-heading"><h2>Approvals</h2><span className="number">{data?.approvals.length ?? 0}</span></div>{data?.approvals.length ? <ul>{data.approvals.slice(0, 3).map((approval) => <li key={approval.id}><span>{approval.action_type}</span><time>{approval.status}</time></li>)}</ul> : <EmptyState message="Nothing waiting for approval." />}</div>
        </section></section>}
        {data && data.profile.profile !== null && view === 'settings' && <Onboarding profile={data.profile} onSaved={(profile) => setData((current) => current ? { ...current, profile } : current)} />}
        <InboxModal isOpen={isInboxOpen} onClose={() => setIsInboxOpen(false)} onTasksUpdated={refreshData} />
        <BriefingModal isOpen={isBriefingOpen} onClose={() => setIsBriefingOpen(false)} />
      </main>
    </div>
  );
}

