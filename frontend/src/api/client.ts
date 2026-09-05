const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

export type ProfileResponse = {
  user: { id: number; email: string; full_name: string };
  profile: { id: number; timezone?: string; college?: string; degree?: string; year?: number; cgpa?: number; target_roles?: string; target_companies?: string; skills?: string; preferred_locations?: string; available_study_hours?: number; preferred_study_times?: string; notification_preferences?: string } | null;
};
export type ProfileInput = Omit<NonNullable<ProfileResponse['profile']>, 'id'> & { full_name?: string };

export type Task = { id: number; user_id: number; title: string; description: string | null; deadline: string | null; status: string; priority: string; category: string | null; estimated_effort_hours: number | null; source: string | null; is_confirmed_deadline: boolean; is_overdue: boolean };
export type CalendarEvent = { id: number; user_id: number; task_id: number | null; title: string; description: string | null; starts_at: string; ends_at: string; event_type: string; location: string | null };
export type CalendarEventInput = Omit<CalendarEvent, 'id' | 'user_id'>;
export type Conflict = { has_conflict: boolean; reasons: string[] };
export type Approval = { id: number; action_type: string; description: string; metadata_json?: string | null; expires_at?: string | null; result_json?: string | null; status: string };
export type Assignment = { id: number; course_name: string; title: string; description: string | null; due_at: string; status: string };
export type Exam = { id: number; course_name: string; title: string; starts_at: string; notes: string | null };
export type StudySession = { id: number; topic: string; task_id: number | null; planned_start: string; planned_end: string; actual_start: string | null; actual_end: string | null; status: string };
export type StudyPlan = { id: number; title: string; target_date: string | null; plan: Record<string, unknown>; status: string };
export type Opportunity = { id: number; title: string; company: string; description: string; required_skills: string | null; match_score: number | null; source: string };
export type DSAProgress = {
  username?: string;
  total: number;
  easy_solved?: number;
  medium_solved?: number;
  hard_solved?: number;
  streak: number;
  active_days?: number;
  ranking?: number | null;
  last_polled_at?: string | null;
  topics: Record<string, number>;
  weak_topics: string[];
  problems: Array<{ id: number; title: string; topic: string; difficulty: string; solved_on: string; needs_revision: boolean }>;
};

export type JobApplicationDSASummary = {
  application_id: number;
  opportunity_id: number;
  company: string;
  role: string;
  status: string;
  total_planned: number;
  solved_count: number;
  remaining_count: number;
  completion_percentage: number;
};

export type JobDSAProblemItem = {
  id: number;
  title: string;
  title_slug: string;
  topic: string;
  difficulty: string;
  company: string;
  notes?: string | null;
  is_solved: boolean;
  solved_on?: string | null;
  leetcode_url?: string | null;
};

export type JobDSAPlanDetails = {
  application_id: number;
  opportunity_id: number;
  company: string;
  role: string;
  status: string;
  total_planned: number;
  solved_count: number;
  remaining_count: number;
  completion_percentage: number;
  planned_problems: JobDSAProblemItem[];
  solved_problems: JobDSAProblemItem[];
  remaining_problems: JobDSAProblemItem[];
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export type InboxProcessResponse = {
  workflow_id: string;
  status: string;
  summary: string;
  total_extracted: number;
  tasks_created: Array<{ id: number | null; title: string; deadline: string | null; priority: string; category: string | null }>;
  skipped_duplicates: string[];
  detected_conflicts: Array<{ task_title: string; deadline: string; conflicts: Array<{ id: number; title: string; starts_at: string; ends_at: string }> }>;
  dry_run: boolean;
};

export type MorningBriefingResponse = {
  workflow_id: string;
  status: string;
  student_name: string;
  briefing: {
    greeting: string;
    quote_or_motto: string | null;
    top_priorities: string[];
    schedule_overview: string;
    urgent_alerts: string[];
    recommended_recovery_action: string | null;
  };
  formatted_text: string;
  delivery_status: string;
  mocked_delivery: boolean;
  tasks_count: number;
  events_today_count: number;
};

export type ActiveJobPipelineItem = {
  id: number;
  user_id: number;
  title: string;
  company: string;
  description: string;
  source: string;
  url: string | null;
  match_score: number | null;
  readiness_score: number | null;
  role_match: string | null;
  matched_role: string | null;
  required_skills: string[];
  technical_strengths: string[];
  developing_topics: string[];
  sop_draft: string | null;
  sop_status: string;
  sop_generated_from: string[];
  student_preferences: { tone_preference?: string; specific_points?: string } | null;
  experience_level: string | null;
  responsibilities: string[];
  company_values: string | null;
  deadline: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type JobActivityItem = {
  id: number;
  activity_type: string;
  message: string;
  metadata: Record<string, any>;
  created_at: string | null;
};

export const api = {
  getProfile: () => request<ProfileResponse>('/profile'),
  saveProfile: (profile: ProfileInput, id?: number) => request<ProfileResponse>(id ? `/profile/${id}` : '/profile', { method: id ? 'PUT' : 'POST', body: JSON.stringify(profile) }),
  getTasks: () => request<Task[]>('/tasks'),
  createTask: (task: Omit<Task, 'id' | 'user_id' | 'is_overdue'>) => request<Task>('/tasks', { method: 'POST', body: JSON.stringify(task) }),
  updateTask: (id: number, task: Partial<Omit<Task, 'id' | 'user_id' | 'is_overdue'>>) => request<Task>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify(task) }),
  deleteTask: (id: number) => request<void>(`/tasks/${id}`, { method: 'DELETE' }),
  getCalendar: () => request<CalendarEvent[]>('/calendar'),
  checkCalendarConflicts: (event: CalendarEventInput) => request<Conflict>('/calendar/conflicts', { method: 'POST', body: JSON.stringify(event) }),
  createCalendarEvent: (event: CalendarEventInput) => request<CalendarEvent>('/calendar/events', { method: 'POST', body: JSON.stringify(event) }),
  getApprovals: () => request<Approval[]>('/approvals'),
  createApproval: (approval: { action_type: string; description: string; metadata_json?: string; expires_at?: string }) => request<Approval>('/approvals', { method: 'POST', body: JSON.stringify(approval) }),
  approve: (id: number) => request<Approval>(`/approvals/${id}/approve`, { method: 'PUT', body: '{}' }),
  reject: (id: number) => request<Approval>(`/approvals/${id}/reject`, { method: 'PUT', body: '{}' }),
  getAssignments: () => request<Assignment[]>('/academic/assignments'),
  getExams: () => request<Exam[]>('/academic/exams'),
  getStudyPlans: () => request<StudyPlan[]>('/academic/study-plans'),
  getStudySessions: () => request<StudySession[]>('/academic/study-sessions'),
  getOpportunities: () => request<Opportunity[]>('/opportunities'),
  getDsa: () => request<DSAProgress>('/dsa'),
  getDsaRecommendations: () => request<{ topics: string[]; recommendation: string }>('/dsa/recommendations'),
  syncLeetCode: () => request<{ status: string; username: string; total_solved: number; newly_solved_count: number }>('/dsa/leetcode/sync', { method: 'POST' }),
  getDsaJobApplications: () => request<JobApplicationDSASummary[]>('/dsa/job-applications'),
  getDsaJobPlan: (applicationId: number) => request<JobDSAPlanDetails>(`/dsa/job-applications/${applicationId}/plan`),
  getDSARoles: () => request<{ roles: Record<string, any> }>('/dsa/roles'),
  getDSAReadiness: (roleName: string) => request<any>(`/dsa/readiness/${encodeURIComponent(roleName)}`),
  // Job Agent & SOP Pipeline API
  getJobPipeline: () => request<ActiveJobPipelineItem[]>('/jobs/pipeline'),
  getJobPipelineItem: (id: number) => request<ActiveJobPipelineItem>(`/jobs/pipeline/${id}`),
  processJobPosting: (payload: { job_text: string; company?: string; title?: string; tone_preference?: string; specific_points?: string }) =>
    request<ActiveJobPipelineItem>('/jobs/pipeline/process', { method: 'POST', body: JSON.stringify(payload) }),
  updateSOP: (id: number, sop_draft: string, sop_status = 'reviewed') =>
    request<ActiveJobPipelineItem>(`/jobs/pipeline/${id}/sop`, { method: 'PUT', body: JSON.stringify({ sop_draft, sop_status }) }),
  regenerateSOP: (id: number, tone_preference?: string, specific_points?: string) =>
    request<ActiveJobPipelineItem>(`/jobs/pipeline/${id}/regenerate-sop`, { method: 'POST', body: JSON.stringify({ tone_preference, specific_points }) }),
  getJobActivity: () => request<JobActivityItem[]>('/jobs/activity'),
  processInbox: (content: string, source_type = 'email') => request<InboxProcessResponse>('/inbox/process', { method: 'POST', body: JSON.stringify({ content, source_type }) }),
  previewInbox: (content: string, source_type = 'email') => request<InboxProcessResponse>('/inbox/preview', { method: 'POST', body: JSON.stringify({ content, source_type }) }),
  generateBriefing: (send_notification = false, chat_id?: string) => request<MorningBriefingResponse>('/workflows/morning-briefing', { method: 'POST', body: JSON.stringify({ send_notification, chat_id }) }),
  getNotifications: () => request<Array<{ id: number; type: string; message: string; metadata: string | null; created_at: string }>>('/notifications'),
};
