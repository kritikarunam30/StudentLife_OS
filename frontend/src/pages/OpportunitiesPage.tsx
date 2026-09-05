import { useEffect, useState } from 'react';
import {
  api,
  type ActiveJobPipelineItem,
  type JobActivityItem,
} from '../api/client';

export default function OpportunitiesPage() {
  const [pipelineJobs, setPipelineJobs] = useState<ActiveJobPipelineItem[]>([]);
  const [activities, setActivities] = useState<JobActivityItem[]>([]);
  const [dsaRoles, setDsaRoles] = useState<Record<string, any>>({});
  const [activeTab, setActiveTab] = useState<'pipeline' | 'roles' | 'activity'>('pipeline');
  const [expandedSOPId, setExpandedSOPId] = useState<number | null>(null);
  const [editingSOPId, setEditingSOPId] = useState<number | null>(null);
  const [editedSOPText, setEditedSOPText] = useState<string>('');
  const [copyNoticeId, setCopyNoticeId] = useState<number | null>(null);

  // Ingestion Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [jobText, setJobText] = useState('');
  const [companyInput, setCompanyInput] = useState('');
  const [titleInput, setTitleInput] = useState('');
  const [tonePreference, setTonePreference] = useState<'formal' | 'conversational'>('formal');
  const [specificPoints, setSpecificPoints] = useState('');
  const [processStatusNotice, setProcessStatusNotice] = useState<string | null>(null);

  // Selected DSA Role for Role Tab View
  const [selectedRoleTab, setSelectedRoleTab] = useState<string>('Software Engineer');
  const [selectedRoleReadiness, setSelectedRoleReadiness] = useState<any>(null);

  const fetchPipeline = () => {
    api.getJobPipeline().then((data) => {
      setPipelineJobs(data);
      if (data.length > 0 && expandedSOPId === null) {
        setExpandedSOPId(data[0].id);
      }
    }).catch(() => setPipelineJobs([]));
  };

  const fetchActivities = () => {
    api.getJobActivity().then(setActivities).catch(() => setActivities([]));
  };

  const fetchRoles = () => {
    api.getDSARoles().then((res) => setDsaRoles(res.roles || {})).catch(() => setDsaRoles({}));
  };

  useEffect(() => {
    fetchPipeline();
    fetchActivities();
    fetchRoles();
  }, []);

  useEffect(() => {
    if (selectedRoleTab) {
      api.getDSAReadiness(selectedRoleTab).then(setSelectedRoleReadiness).catch(() => setSelectedRoleReadiness(null));
    }
  }, [selectedRoleTab]);

  const handleProcessJob = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jobText.trim()) return;
    setIsProcessing(true);
    setProcessStatusNotice(null);

    try {
      const createdJob = await api.processJobPosting({
        job_text: jobText,
        company: companyInput.trim() || undefined,
        title: titleInput.trim() || undefined,
        tone_preference: tonePreference,
        specific_points: specificPoints.trim() || undefined,
      });

      if (createdJob.sop_status !== 'discarded') {
        setProcessStatusNotice(`Successfully analyzed ${createdJob.company}! SOP Status: ${createdJob.sop_status.toUpperCase()}`);
      }
      fetchPipeline();
      fetchActivities();
      setIsModalOpen(false);
      setJobText('');
      setCompanyInput('');
      setTitleInput('');
      setSpecificPoints('');
      if (createdJob.sop_status !== 'discarded') {
        setExpandedSOPId(createdJob.id);
      }
    } catch (err: any) {
      setProcessStatusNotice(`Error processing job: ${err?.message || 'Failed to analyze'}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSaveSOP = async (jobId: number) => {
    try {
      const updated = await api.updateSOP(jobId, editedSOPText, 'reviewed');
      setPipelineJobs((prev) => prev.map((j) => (j.id === jobId ? updated : j)));
      setEditingSOPId(null);
      fetchActivities();
    } catch {
      alert('Failed to save SOP updates.');
    }
  };

  const handleRegenerateSOP = async (jobId: number, tone: string) => {
    try {
      const updated = await api.regenerateSOP(jobId, tone);
      setPipelineJobs((prev) => prev.map((j) => (j.id === jobId ? updated : j)));
      fetchActivities();
    } catch {
      alert('Failed to regenerate SOP draft.');
    }
  };

  const handleCopySOP = (jobId: number, text: string) => {
    navigator.clipboard.writeText(text);
    setCopyNoticeId(jobId);
    setTimeout(() => setCopyNoticeId(null), 2500);
  };

  const handleExportSOP = (job: ActiveJobPipelineItem) => {
    const filename = `SOP_${job.company.replace(/\s+/g, '_')}_${job.title.replace(/\s+/g, '_')}.txt`;
    const element = document.createElement('a');
    const file = new Blob([job.sop_draft || ''], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = filename;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  const totalTracked = pipelineJobs.length;
  const totalSOPs = pipelineJobs.filter((j) => j.sop_draft && j.sop_status !== 'discarded').length;
  const technicalJobs = pipelineJobs.filter((j) => j.readiness_score != null);
  const avgReadiness = technicalJobs.length > 0
    ? Math.round(technicalJobs.reduce((acc, j) => acc + (j.readiness_score || 0), 0) / technicalJobs.length)
    : 0;

  return (
    <section>
      {/* Top Header */}
      <div className="section-heading">
        <div>
          <p className="eyebrow">Autonomous Career Agent</p>
          <h2>Job Pipeline & Tailored SOP Studio</h2>
        </div>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            className="primary-button"
            onClick={() => setIsModalOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            ⚡ Ingest Job Posting
          </button>
        </div>
      </div>

      {processStatusNotice && (
        <div className="notice" style={{ marginTop: '12px', background: '#18222b', borderColor: '#f2b84b' }}>
          {processStatusNotice}
        </div>
      )}

      {/* KPI Overview Metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', margin: '20px 0' }}>
        <div className="card" style={{ padding: '16px' }}>
          <span className="eyebrow">Jobs Evaluated</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#e9edf5', marginTop: '4px' }}>
            {totalTracked}
          </div>
          <span className="muted" style={{ fontSize: '0.75rem' }}>Parsed & role-mapped</span>
        </div>
        <div className="card" style={{ padding: '16px' }}>
          <span className="eyebrow">Autonomous SOPs</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#67d391', marginTop: '4px' }}>
            {totalSOPs}
          </div>
          <span className="muted" style={{ fontSize: '0.75rem' }}>Tailored & grounded drafts</span>
        </div>
        <div className="card" style={{ padding: '16px' }}>
          <span className="eyebrow">Avg DSA Readiness</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#f2b84b', marginTop: '4px' }}>
            {avgReadiness}%
          </div>
          <span className="muted" style={{ fontSize: '0.75rem' }}>Across matched roles</span>
        </div>
      </div>

      {/* Primary Tab Switcher */}
      <div style={{ display: 'flex', gap: '10px', borderBottom: '1px solid #2a3540', paddingBottom: '12px', marginBottom: '20px' }}>
        <button
          className={activeTab === 'pipeline' ? 'primary-button' : 'secondary-button'}
          onClick={() => setActiveTab('pipeline')}
          style={{ padding: '8px 16px', fontSize: '0.9rem' }}
        >
          💼 Active Job Pipeline ({pipelineJobs.length})
        </button>
        <button
          className={activeTab === 'roles' ? 'primary-button' : 'secondary-button'}
          onClick={() => setActiveTab('roles')}
          style={{ padding: '8px 16px', fontSize: '0.9rem' }}
        >
          🎯 DSA Role Requirements Tabs
        </button>
        <button
          className={activeTab === 'activity' ? 'primary-button' : 'secondary-button'}
          onClick={() => {
            setActiveTab('activity');
            fetchActivities();
          }}
          style={{ padding: '8px 16px', fontSize: '0.9rem' }}
        >
          📡 Live Activity Stream ({activities.length})
        </button>
      </div>

      {/* TAB 1: Job Pipeline & SOP Studio */}
      {activeTab === 'pipeline' && (
        <div>
          {pipelineJobs.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', padding: '40px 20px' }}>
              <p className="empty-state">No jobs in the active pipeline yet.</p>
              <button className="primary-button" onClick={() => setIsModalOpen(true)} style={{ marginTop: '12px' }}>
                Ingest your first job description
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {pipelineJobs.map((job) => {
                const isExpanded = expandedSOPId === job.id;
                const isEditing = editingSOPId === job.id;
                const isDiscarded = job.sop_status === 'discarded';

                return (
                  <article
                    key={job.id}
                    className="card"
                    style={{
                      border: isExpanded ? '1px solid #f2b84b' : '1px solid #283440',
                      background: isExpanded ? 'rgba(24, 34, 43, 0.95)' : '#161e27',
                      padding: '20px',
                      borderRadius: '8px',
                    }}
                  >
                    {/* Job Card Top Header */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <h3 style={{ margin: 0, fontSize: '1.25rem', color: '#e9edf5' }}>{job.title}</h3>
                          <span
                            style={{
                              fontSize: '0.75rem',
                              padding: '2px 8px',
                              borderRadius: '4px',
                              background: '#23303d',
                              color: '#f2b84b',
                              fontFamily: 'Space Mono',
                            }}
                          >
                            {job.company}
                          </span>
                          <span
                            style={{
                              fontSize: '0.7rem',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              background: job.role_match === 'exact' ? 'rgba(103, 211, 145, 0.15)' : 'rgba(242, 184, 75, 0.15)',
                              color: job.role_match === 'exact' ? '#67d391' : '#f2b84b',
                            }}
                          >
                            {job.matched_role} ({job.role_match})
                          </span>
                        </div>
                        <p className="muted" style={{ margin: '6px 0 0', fontSize: '0.85rem' }}>
                          {job.experience_level || 'Internship / Entry Level'} {job.deadline ? `· Deadline: ${job.deadline}` : ''}
                        </p>
                      </div>

                      {/* Score Badges */}
                      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                        <div style={{ textAlign: 'right' }}>
                          <span style={{ fontSize: '0.75rem', color: '#82909d', display: 'block' }}>Fit Match</span>
                          <strong style={{ fontSize: '1.1rem', color: '#67d391', fontFamily: 'Space Mono' }}>
                            {Math.round(job.match_score || 0)}%
                          </strong>
                        </div>
                        <div style={{ textAlign: 'right', borderLeft: '1px solid #283440', paddingLeft: '12px' }}>
                          <span style={{ fontSize: '0.75rem', color: '#82909d', display: 'block' }}>DSA Readiness</span>
                          <strong style={{ fontSize: '1.1rem', color: (job.readiness_score || 0) >= 75 ? '#67d391' : '#f2b84b', fontFamily: 'Space Mono' }}>
                            {job.readiness_score == null ? 'N/A' : `${job.readiness_score}%`}
                          </strong>
                        </div>
                      </div>
                    </div>

                    {/* Requirements are sourced from this same persisted job record. */}
                    <div style={{ margin: '14px 0 0', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.75rem', color: '#82909d' }}>Job Requirements:</span>
                      {job.required_skills.length > 0 ? (
                        job.required_skills.map((skill, idx) => (
                          <span key={idx} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px', background: 'rgba(242, 184, 75, 0.12)', color: '#f2b84b' }}>
                            {skill}
                          </span>
                        ))
                      ) : (
                        <span style={{ fontSize: '0.75rem', color: '#82909d' }}>Not applicable</span>
                      )}
                    </div>

                    {/* Strengths & Weaknesses Breakdown */}
                    <div style={{ margin: '14px 0', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.75rem', color: '#82909d' }}>Verified Strengths:</span>
                      {job.technical_strengths && job.technical_strengths.length > 0 ? (
                        job.technical_strengths.map((s, idx) => (
                          <span key={idx} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px', background: 'rgba(103, 211, 145, 0.12)', color: '#67d391' }}>
                            ✓ {s}
                          </span>
                        ))
                      ) : (
                        <span style={{ fontSize: '0.75rem', color: '#82909d' }}>None</span>
                      )}

                      {job.developing_topics && job.developing_topics.length > 0 && (
                        <>
                          <span style={{ fontSize: '0.75rem', color: '#82909d', marginLeft: '10px' }}>Developing:</span>
                          {job.developing_topics.map((d, idx) => (
                            <span key={idx} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px', background: 'rgba(240, 162, 162, 0.15)', color: '#f0a2a2' }}>
                              ⚠ {d}
                            </span>
                          ))}
                        </>
                      )}
                    </div>

                    {/* Discarded Notice */}
                    {isDiscarded && (
                      <div style={{ background: 'rgba(240, 162, 162, 0.1)', border: '1px solid #f0a2a2', padding: '10px 14px', borderRadius: '6px', fontSize: '0.85rem', color: '#f0a2a2', margin: '12px 0' }}>
                        ❌ <strong>Job Discarded:</strong> Match score is below 60% threshold. The Job Agent discarded this posting without generating an SOP to preserve focus.
                      </div>
                    )}

                    {/* Toggle Button for SOP */}
                    {!isDiscarded && (
                      <div style={{ marginTop: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #283440', paddingTop: '12px' }}>
                        <button
                          className="secondary-button"
                          onClick={() => setExpandedSOPId(isExpanded ? null : job.id)}
                          style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}
                        >
                          {isExpanded ? '▲ Hide SOP Draft' : '▼ View Tailored Statement of Purpose (SOP)'}
                          <span
                            style={{
                              fontSize: '0.7rem',
                              padding: '1px 6px',
                              borderRadius: '3px',
                              background: job.sop_status === 'reviewed' ? 'rgba(103, 211, 145, 0.2)' : 'rgba(242, 184, 75, 0.2)',
                              color: job.sop_status === 'reviewed' ? '#67d391' : '#f2b84b',
                            }}
                          >
                            {job.sop_status.toUpperCase()}
                          </span>
                        </button>

                        <div style={{ display: 'flex', gap: '8px' }}>
                          {isExpanded && (
                            <>
                              <button
                                className="secondary-button"
                                onClick={() => {
                                  if (isEditing) {
                                    handleSaveSOP(job.id);
                                  } else {
                                    setEditingSOPId(job.id);
                                    setEditedSOPText(job.sop_draft || '');
                                  }
                                }}
                                style={{ fontSize: '0.8rem', padding: '4px 10px' }}
                              >
                                {isEditing ? '💾 Save Changes' : '✏️ Edit Draft'}
                              </button>
                              <button
                                className="secondary-button"
                                onClick={() => handleCopySOP(job.id, job.sop_draft || '')}
                                style={{ fontSize: '0.8rem', padding: '4px 10px' }}
                              >
                                {copyNoticeId === job.id ? '✓ Copied!' : '📋 Copy'}
                              </button>
                              <button
                                className="secondary-button"
                                onClick={() => handleExportSOP(job)}
                                style={{ fontSize: '0.8rem', padding: '4px 10px' }}
                              >
                                📥 Export .txt
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Expandable SOP Section */}
                    {isExpanded && !isDiscarded && (
                      <div style={{ marginTop: '16px', background: '#0e141a', padding: '16px', borderRadius: '6px', border: '1px solid #23303d' }}>
                        {isEditing ? (
                          <div>
                              <textarea
                              value={editedSOPText}
                              onChange={(e) => setEditedSOPText(e.target.value)}
                              rows={12}
                              style={{
                                width: '100%',
                                background: '#161e27',
                                color: '#e9edf5',
                                border: '1px solid #2f3e4e',
                                borderRadius: '4px',
                                padding: '12px',
                                fontFamily: 'inherit',
                                fontSize: '1rem',
                                lineHeight: '1.8',
                              }}
                            />
                            <div style={{ marginTop: '10px', display: 'flex', gap: '8px' }}>
                              <button className="primary-button" onClick={() => handleSaveSOP(job.id)} style={{ fontSize: '0.85rem' }}>
                                Save & Update Status
                              </button>
                              <button className="secondary-button" onClick={() => setEditingSOPId(null)} style={{ fontSize: '0.85rem' }}>
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="sop-draft" style={{ whiteSpace: 'pre-line', color: '#cbd5e1' }}>
                            {job.sop_draft}
                          </div>
                        )}

                        {/* Explainability Provenance Caption */}
                        {job.sop_generated_from && job.sop_generated_from.length > 0 && (
                          <div
                            style={{
                              marginTop: '16px',
                              paddingTop: '12px',
                              borderTop: '1px dashed #283440',
                              fontSize: '0.75rem',
                              color: '#82909d',
                            }}
                          >
                            <span style={{ fontWeight: 600, color: '#f2b84b' }}>📌 Generated from verified data: </span>
                            {job.sop_generated_from.join(' · ')}
                          </div>
                        )}

                        {/* Quick Tone Re-drafting controls */}
                        <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.8rem', color: '#82909d' }}>
                          <span>Re-draft with AI:</span>
                          <button
                            className="secondary-button"
                            onClick={() => handleRegenerateSOP(job.id, 'formal')}
                            style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                          >
                            Formal Achievement
                          </button>
                          <button
                            className="secondary-button"
                            onClick={() => handleRegenerateSOP(job.id, 'conversational')}
                            style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                          >
                            Conversational Trajectory
                          </button>
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* TAB 2: Per-Role DSA Requirements Explorer */}
      {activeTab === 'roles' && (
        <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: '20px' }}>
          {/* Left Role Tabs */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {Object.keys(dsaRoles).map((roleName) => (
              <button
                key={roleName}
                onClick={() => setSelectedRoleTab(roleName)}
                style={{
                  padding: '12px 16px',
                  borderRadius: '6px',
                  textAlign: 'left',
                  border: selectedRoleTab === roleName ? '1px solid #f2b84b' : '1px solid #283440',
                  background: selectedRoleTab === roleName ? '#18222b' : '#141c24',
                  color: selectedRoleTab === roleName ? '#fff' : '#a9b5c0',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                }}
              >
                {roleName}
              </button>
            ))}
          </div>

          {/* Right Role Breakdown */}
          {selectedRoleReadiness ? (
            <div className="card feature-card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">DSA Requirement Benchmark</span>
                  <h2>{selectedRoleReadiness.matched_role}</h2>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span className="muted" style={{ fontSize: '0.8rem', display: 'block' }}>Student Technical Readiness</span>
                  <strong style={{ fontSize: '1.4rem', color: selectedRoleReadiness.readiness_score >= 75 ? '#67d391' : '#f2b84b', fontFamily: 'Space Mono' }}>
                    {selectedRoleReadiness.readiness_score}%
                  </strong>
                </div>
              </div>

              <div style={{ marginTop: '20px' }}>
                <h4 style={{ fontSize: '0.95rem', color: '#e9edf5', marginBottom: '12px' }}>Required Topics & Verified Confidence</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {selectedRoleReadiness.topic_breakdown?.map((t: any, idx: number) => {
                    const pct = Math.round(t.confidence * 100);
                    return (
                      <div key={idx} style={{ background: '#121921', padding: '12px 16px', borderRadius: '6px', border: '1px solid #24303c' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '0.85rem' }}>
                          <strong style={{ color: '#e9edf5' }}>{t.topic}</strong>
                          <span style={{ color: t.confidence >= 0.6 ? '#67d391' : '#f2b84b', fontFamily: 'Space Mono' }}>
                            {pct}% ({t.status.toUpperCase()})
                          </span>
                        </div>
                        <div style={{ width: '100%', height: '6px', background: '#24303c', borderRadius: '3px', overflow: 'hidden' }}>
                          <div
                            style={{
                              width: `${pct}%`,
                              height: '100%',
                              background: t.confidence >= 0.6 ? '#67d391' : '#f2b84b',
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="card" style={{ padding: '20px', textAlign: 'center' }}>
              <p className="empty-state">Loading role requirements...</p>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: Live Decision Stream (Activity Feed) */}
      {activeTab === 'activity' && (
        <div className="card feature-card">
          <div className="card-heading">
            <div>
              <span className="eyebrow">Audit & Explainability Feed</span>
              <h2>Job Agent Decision Stream</h2>
            </div>
            <button className="secondary-button" onClick={fetchActivities} style={{ fontSize: '0.8rem' }}>
              🔄 Refresh
            </button>
          </div>

          <div style={{ marginTop: '16px' }}>
            {activities.length === 0 ? (
              <p className="empty-state">No career activity logged yet. Process a job posting to see autonomous decision steps.</p>
            ) : (
              <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {activities.map((act) => (
                  <li
                    key={act.id}
                    style={{
                      background: '#121921',
                      borderLeft: '4px solid #f2b84b',
                      padding: '12px 16px',
                      borderRadius: '0 6px 6px 0',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span
                        style={{
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          color: '#f2b84b',
                        }}
                      >
                        {act.activity_type.replace(/_/g, ' ')}
                      </span>
                      <span className="muted" style={{ fontSize: '0.75rem' }}>
                        {act.created_at ? new Date(act.created_at).toLocaleTimeString() : ''}
                      </span>
                    </div>
                    <p style={{ margin: '6px 0 0', fontSize: '0.9rem', color: '#e9edf5' }}>{act.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* Ingestion Modal */}
      {isModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '20px',
          }}
        >
          <div
            className="card"
            style={{
              width: '100%',
              maxWidth: '680px',
              maxHeight: '90vh',
              overflowY: 'auto',
              background: '#151d26',
              border: '1px solid #334354',
              padding: '24px',
              borderRadius: '8px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <span className="eyebrow">Autonomous Ingestion</span>
                <h3 style={{ margin: 0, fontSize: '1.25rem', color: '#e9edf5' }}>Ingest & Evaluate Job Opportunity</h3>
              </div>
              <button
                className="secondary-button"
                onClick={() => setIsModalOpen(false)}
                style={{ padding: '4px 10px', fontSize: '0.85rem' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleProcessJob} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '0.8rem', color: '#a9b5c0', display: 'block', marginBottom: '4px' }}>
                    Company Name (optional)
                  </label>
                  <input
                    type="text"
                    value={companyInput}
                    onChange={(e) => setCompanyInput(e.target.value)}
                    placeholder="e.g. Google, DeepTech AI"
                    style={{ width: '100%', padding: '8px 12px', background: '#1c2631', border: '1px solid #2f3e4e', borderRadius: '4px', color: '#fff' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '0.8rem', color: '#a9b5c0', display: 'block', marginBottom: '4px' }}>
                    Target Role Title (optional)
                  </label>
                  <input
                    type="text"
                    value={titleInput}
                    onChange={(e) => setTitleInput(e.target.value)}
                    placeholder="e.g. ML Engineer Intern"
                    style={{ width: '100%', padding: '8px 12px', background: '#1c2631', border: '1px solid #2f3e4e', borderRadius: '4px', color: '#fff' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: '#a9b5c0', display: 'block', marginBottom: '4px' }}>
                  Raw Job Description or Posting Text *
                </label>
                <textarea
                  value={jobText}
                  onChange={(e) => setJobText(e.target.value)}
                  rows={6}
                  required
                  placeholder="Paste complete job description, responsibilities, and qualifications..."
                  style={{ width: '100%', padding: '10px 12px', background: '#1c2631', border: '1px solid #2f3e4e', borderRadius: '4px', color: '#fff', fontSize: '0.85rem' }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '0.8rem', color: '#a9b5c0', display: 'block', marginBottom: '4px' }}>
                    SOP Tone
                  </label>
                  <select
                    value={tonePreference}
                    onChange={(e) => setTonePreference(e.target.value as any)}
                    style={{ width: '100%', padding: '8px 12px', background: '#1c2631', border: '1px solid #2f3e4e', borderRadius: '4px', color: '#fff' }}
                  >
                    <option value="formal">Formal & Rigorous</option>
                    <option value="conversational">Conversational & Passionate</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '0.8rem', color: '#a9b5c0', display: 'block', marginBottom: '4px' }}>
                    Specific Student Notes to Emphasize
                  </label>
                  <input
                    type="text"
                    value={specificPoints}
                    onChange={(e) => setSpecificPoints(e.target.value)}
                    placeholder="e.g. Mention LeetCode streak, recent project on FastAPI"
                    style={{ width: '100%', padding: '8px 12px', background: '#1c2631', border: '1px solid #2f3e4e', borderRadius: '4px', color: '#fff' }}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setIsModalOpen(false)}
                  disabled={isProcessing}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="primary-button"
                  disabled={isProcessing || !jobText.trim()}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  {isProcessing ? '⚡ Autonomously Processing...' : '✨ Run Job Agent & Draft SOP'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}