import type { Assignment, Exam, StudyPlan } from '../api/client';

type Props = { assignments: Assignment[]; exams: Exam[]; studyPlans: StudyPlan[] };

function uniqueById<T extends { id: number }>(records: T[]): T[] {
  return Array.from(new Map(records.map((record) => [record.id, record])).values());
}

export default function AcademicPage({ assignments: rawAssignments, exams: rawExams, studyPlans: rawStudyPlans }: Props) {
  const assignments = uniqueById(rawAssignments);
  const exams = uniqueById(rawExams);
  const studyPlans = uniqueById(rawStudyPlans);

  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Academic command center</p>
          <h2>Academic work</h2>
        </div>
        <span className="muted">{studyPlans.length} study plans</span>
      </div>

      <div className="grid">
        <div className="card">
          <div className="card-heading">
            <h2>Assignments</h2>
            <span className="number">{assignments.length}</span>
          </div>
          {assignments.length ? assignments.map((item) => (
            <p key={item.id}>
              <strong>{item.title}</strong><br />
              <span className="muted">
                {item.course_name} · due {new Date(item.due_at).toLocaleDateString()}
              </span>
            </p>
          )) : <p className="empty-state muted">No assignments found.</p>}
        </div>

        <div className="card">
          <div className="card-heading">
            <h2>Exams</h2>
            <span className="number">{exams.length}</span>
          </div>
          {exams.length ? exams.map((item) => (
            <p key={item.id}>
              <strong>{item.title}</strong><br />
              <span className="muted">
                {item.course_name} · {new Date(item.starts_at).toLocaleDateString()}
              </span>
            </p>
          )) : <p className="empty-state muted">No exams found.</p>}
        </div>

        <div className="card">
          <div className="card-heading">
            <h2>Study plan</h2>
            <span className="number">{studyPlans.length}</span>
          </div>
          {studyPlans.length ? studyPlans.map((item) => (
            <p key={item.id}>
              <strong>{item.title}</strong><br />
              <span className="muted">
                {item.status}
                {item.target_date ? ` · ${new Date(item.target_date).toLocaleDateString()}` : ''}
              </span>
            </p>
          )) : <p className="empty-state muted">No study items found.</p>}
        </div>
      </div>
    </section>
  );
}
