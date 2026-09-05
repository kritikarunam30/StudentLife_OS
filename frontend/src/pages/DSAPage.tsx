import { useEffect, useState } from 'react';
import { api, type DSAProgress, type JobApplicationDSASummary, type JobDSAPlanDetails } from '../api/client';

export default function DSAPage() {
  const [activeTab, setActiveTab] = useState<'leetcode' | 'jobs'>('leetcode');
  const [dsaData, setDsaData] = useState<DSAProgress | null>(null);
  const [jobApplications, setJobApplications] = useState<JobApplicationDSASummary[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<number | null>(null);
  const [jobPlanDetails, setJobPlanDetails] = useState<JobDSAPlanDetails | null>(null);
  const [problemFilter, setProblemFilter] = useState<'all' | 'solved' | 'remaining'>('all');
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);

  const fetchDsaData = () => {
    api.getDsa().then(setDsaData).catch(() => setDsaData(null));
  };

  const fetchJobApplications = () => {
    api.getDsaJobApplications().then((apps) => {
      setJobApplications(apps);
      if (apps.length > 0 && selectedAppId === null) {
        setSelectedAppId(apps[0].application_id);
      }
    }).catch(() => setJobApplications([]));
  };

  useEffect(() => {
    fetchDsaData();
    fetchJobApplications();
  }, []);

  useEffect(() => {
    if (selectedAppId !== null) {
      api.getDsaJobPlan(selectedAppId).then(setJobPlanDetails).catch(() => setJobPlanDetails(null));
    }
  }, [selectedAppId]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncNotice(null);
    try {
      const res = await api.syncLeetCode();
      setSyncNotice(`Synced @${res.username}! ${res.newly_solved_count} new accepted submission(s) recorded.`);
      fetchDsaData();
      fetchJobApplications();
      if (selectedAppId !== null) {
        api.getDsaJobPlan(selectedAppId).then(setJobPlanDetails).catch(() => {});
      }
    } catch {
      setSyncNotice('Failed to sync with LeetCode. Please try again.');
    } finally {
      setSyncing(false);
    }
  };

  const selectedJobSummary = jobApplications.find((app) => app.application_id === selectedAppId);

  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Practice Ledger & Career Readiness</p>
          <h2>DSA Tracking & Job Prep</h2>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span className="number" style={{ fontSize: '1rem' }}>
            🔥 {dsaData?.streak || 0} Day Streak
          </span>
          <button
            className="secondary-button"
            onClick={handleSync}
            disabled={syncing}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            {syncing ? 'Syncing LeetCode...' : '⚡ Sync LeetCode'}
          </button>
        </div>
      </div>

      {syncNotice && (
        <div className="notice" style={{ marginTop: '12px', background: '#18222b', borderColor: '#f2b84b' }}>
          {syncNotice}
        </div>
      )}

      {/* Primary Section Switcher */}
      <div style={{ display: 'flex', gap: '8px', margin: '20px 0 24px', borderBottom: '1px solid #2a3540', paddingBottom: '12px' }}>
        <button
          className={activeTab === 'leetcode' ? 'primary-button' : 'secondary-button'}
          onClick={() => setActiveTab('leetcode')}
          style={{ padding: '8px 16px', fontSize: '0.9rem' }}
        >
          📊 LeetCode Live Progress
        </button>
        <button
          className={activeTab === 'jobs' ? 'primary-button' : 'secondary-button'}
          onClick={() => setActiveTab('jobs')}
          style={{ padding: '8px 16px', fontSize: '0.9rem' }}
        >
          💼 Job Applications Prep ({jobApplications.length})
        </button>
      </div>

      {activeTab === 'leetcode' && (
        <>
          {/* User Profile Header */}
          <div className="card feature-card" style={{ marginBottom: '20px', padding: '18px 22px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
              <div>
                <span className="eyebrow" style={{ fontSize: '0.7rem' }}>Connected Profile</span>
                <h3 style={{ margin: '4px 0 0', fontSize: '1.2rem', color: '#fff' }}>
                  {dsaData?.username ? `@${dsaData.username}` : 'No LeetCode account connected'}
                </h3>
              </div>
              <div style={{ display: 'flex', gap: '24px', textTransform: 'uppercase', fontSize: '0.75rem', color: '#82909d' }}>
                <div>
                  <span style={{ display: 'block', color: '#a9b5c0' }}>Active Days</span>
                  <strong style={{ fontSize: '1.1rem', color: '#e9edf5' }}>{dsaData?.active_days || 0}</strong>
                </div>
                <div>
                  <span style={{ display: 'block', color: '#a9b5c0' }}>Global Rank</span>
                  <strong style={{ fontSize: '1.1rem', color: '#f2b84b' }}>
                    {dsaData?.ranking ? `#${dsaData.ranking.toLocaleString()}` : 'N/A'}
                  </strong>
                </div>
                <div>
                  <span style={{ display: 'block', color: '#a9b5c0' }}>Last Synced</span>
                  <strong style={{ fontSize: '0.85rem', color: '#67d391' }}>
                    {dsaData?.last_polled_at ? new Date(dsaData.last_polled_at).toLocaleTimeString() : 'Not synced'}
                  </strong>
                </div>
              </div>
            </div>
          </div>

          {/* Stats Grid */}
          <div className="grid">
            <div className="card">
              <h2>Total Solved Problems</h2>
              <p className="number" style={{ margin: '14px 0 8px', fontSize: '2.2rem' }}>
                {dsaData?.total || 0}
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', marginTop: '16px', fontSize: '0.8rem' }}>
                <div style={{ background: 'rgba(103, 211, 145, 0.1)', padding: '8px', borderRadius: '4px', textAlign: 'center' }}>
                  <span style={{ color: '#67d391', fontWeight: 600 }}>Easy</span>
                  <div style={{ fontSize: '1.1rem', marginTop: '2px', color: '#fff' }}>{dsaData?.easy_solved || 0}</div>
                </div>
                <div style={{ background: 'rgba(242, 184, 75, 0.1)', padding: '8px', borderRadius: '4px', textAlign: 'center' }}>
                  <span style={{ color: '#f2b84b', fontWeight: 600 }}>Medium</span>
                  <div style={{ fontSize: '1.1rem', marginTop: '2px', color: '#fff' }}>{dsaData?.medium_solved || 0}</div>
                </div>
                <div style={{ background: 'rgba(240, 162, 162, 0.1)', padding: '8px', borderRadius: '4px', textAlign: 'center' }}>
                  <span style={{ color: '#f0a2a2', fontWeight: 600 }}>Hard</span>
                  <div style={{ fontSize: '1.1rem', marginTop: '2px', color: '#fff' }}>{dsaData?.hard_solved || 0}</div>
                </div>
              </div>
            </div>

            <div className="card">
              <h2>Topics Breakdown</h2>
              {dsaData && Object.keys(dsaData.topics || {}).length > 0 ? (
                <ul style={{ maxHeight: '180px', overflowY: 'auto' }}>
                  {Object.entries(dsaData.topics).map(([topic, count]) => (
                    <li key={topic}>
                      <span>{topic}</span>
                      <span className="number" style={{ fontSize: '0.95rem' }}>{count} solved</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">No topics tracked yet.</p>
              )}
            </div>

            <div className="card">
              <h2>Next Recommendation</h2>
              <p style={{ margin: '14px 0', lineHeight: '1.4', color: '#e9edf5' }}>
                {dsaData?.weak_topics?.length ? `Focus on practicing ${dsaData.weak_topics[0]}.` : 'No recommendations yet.'}
              </p>
              {dsaData?.weak_topics && dsaData.weak_topics.length > 0 ? (
                <>
                  <h3 style={{ marginTop: '14px', fontSize: '0.75rem', color: '#82909d', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Target Practice Topics
                  </h3>
                  <ul>
                    {dsaData.weak_topics.slice(0, 3).map((wt) => (
                      <li key={wt}>
                        <span>{wt}</span>
                        <span style={{ color: '#f0a2a2', fontSize: '0.8rem' }}>Needs practice</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          </div>

          {/* Recent Submissions Ledger */}
          {dsaData?.problems && dsaData.problems.length > 0 && (
            <div className="card feature-card" style={{ marginTop: '24px' }}>
              <div className="card-heading">
                <h2>Recent LeetCode Submissions</h2>
                <span className="date-chip">{dsaData.problems.length} Recorded</span>
              </div>
              <ul>
                {dsaData.problems.map((prob) => (
                  <li key={prob.id} style={{ alignItems: 'center' }}>
                    <div>
                      <strong style={{ color: '#e9edf5' }}>{prob.title}</strong>
                      <span className="muted" style={{ marginLeft: '10px' }}>— {prob.topic}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <span
                        style={{
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          padding: '3px 8px',
                          borderRadius: '4px',
                          textTransform: 'uppercase',
                          background:
                            prob.difficulty.toLowerCase() === 'easy'
                              ? 'rgba(103, 211, 145, 0.15)'
                              : prob.difficulty.toLowerCase() === 'medium'
                              ? 'rgba(242, 184, 75, 0.15)'
                              : 'rgba(240, 162, 162, 0.15)',
                          color:
                            prob.difficulty.toLowerCase() === 'easy'
                              ? '#67d391'
                              : prob.difficulty.toLowerCase() === 'medium'
                              ? '#f2b84b'
                              : '#f0a2a2',
                        }}
                      >
                        {prob.difficulty}
                      </span>
                      <time>{prob.solved_on}</time>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {activeTab === 'jobs' && (
        <div>
          {/* Job Selection Tabs */}
          <div style={{ display: 'flex', gap: '10px', overflowX: 'auto', paddingBottom: '12px', marginBottom: '20px' }}>
            {jobApplications.map((app) => (
              <button
                key={app.application_id}
                onClick={() => {
                  setSelectedAppId(app.application_id);
                  setProblemFilter('all');
                }}
                style={{
                  padding: '12px 18px',
                  borderRadius: '6px',
                  border: selectedAppId === app.application_id ? '1px solid #f2b84b' : '1px solid #2b3843',
                  background: selectedAppId === app.application_id ? '#18222b' : 'rgba(21, 29, 37, 0.8)',
                  color: selectedAppId === app.application_id ? '#fff' : '#a9b5c0',
                  cursor: 'pointer',
                  textAlign: 'left',
                  minWidth: '180px',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{app.company}</div>
                <div style={{ fontSize: '0.75rem', color: '#82909d', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {app.role}
                </div>
                <div style={{ marginTop: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', color: '#f2b84b', fontFamily: 'Space Mono' }}>
                    {app.completion_percentage}%
                  </span>
                  <span style={{ fontSize: '0.75rem', color: '#67d391' }}>
                    {app.solved_count}/{app.total_planned} Solved
                  </span>
                </div>
              </button>
            ))}
          </div>

          {/* Job Plan Details View */}
          {jobPlanDetails ? (
            <div className="card feature-card">
              <div className="card-heading" style={{ flexWrap: 'wrap', gap: '16px' }}>
                <div>
                  <span className="eyebrow">{jobPlanDetails.company} DSA Prep Plan</span>
                  <h2>{jobPlanDetails.role}</h2>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span className="date-chip" style={{ background: 'rgba(103, 211, 145, 0.1)', color: '#67d391', borderColor: '#67d391' }}>
                    Status: {jobPlanDetails.status.toUpperCase()}
                  </span>
                </div>
              </div>

              {/* Progress Meter */}
              <div style={{ background: '#121921', padding: '18px', borderRadius: '6px', margin: '20px 0', border: '1px solid #283440' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.9rem' }}>
                  <span style={{ color: '#a9b5c0' }}>Preparation Progress</span>
                  <strong style={{ color: '#f2b84b', fontFamily: 'Space Mono' }}>
                    {jobPlanDetails.completion_percentage}% ({jobPlanDetails.solved_count} / {jobPlanDetails.total_planned} Solved)
                  </strong>
                </div>
                <div style={{ width: '100%', height: '10px', background: '#263442', borderRadius: '5px', overflow: 'hidden' }}>
                  <div
                    style={{
                      width: `${jobPlanDetails.completion_percentage}%`,
                      height: '100%',
                      background: 'linear-gradient(90deg, #67d391 0%, #f2b84b 100%)',
                      transition: 'width 0.4s ease',
                    }}
                  />
                </div>
                <div style={{ display: 'flex', gap: '20px', marginTop: '12px', fontSize: '0.8rem', color: '#82909d' }}>
                  <span>✅ {jobPlanDetails.solved_count} Solved on LeetCode</span>
                  <span>⏳ {jobPlanDetails.remaining_count} Remaining to practice</span>
                </div>
              </div>

              {/* Problem Filter Sub-Tabs */}
              <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
                <button
                  className={problemFilter === 'all' ? 'primary-button' : 'secondary-button'}
                  onClick={() => setProblemFilter('all')}
                  style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                >
                  All Planned ({jobPlanDetails.total_planned})
                </button>
                <button
                  className={problemFilter === 'solved' ? 'primary-button' : 'secondary-button'}
                  onClick={() => setProblemFilter('solved')}
                  style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                >
                  ✅ Solved ({jobPlanDetails.solved_count})
                </button>
                <button
                  className={problemFilter === 'remaining' ? 'primary-button' : 'secondary-button'}
                  onClick={() => setProblemFilter('remaining')}
                  style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                >
                  ⏳ Remaining ({jobPlanDetails.remaining_count})
                </button>
              </div>

              {/* Problems List */}
              {(() => {
                const problemsToList =
                  problemFilter === 'solved'
                    ? jobPlanDetails.solved_problems
                    : problemFilter === 'remaining'
                    ? jobPlanDetails.remaining_problems
                    : jobPlanDetails.planned_problems;

                if (problemsToList.length === 0) {
                  return <p className="empty-state">No problems found in this view.</p>;
                }

                return (
                  <ul>
                    {problemsToList.map((prob) => (
                      <li key={prob.id} style={{ alignItems: 'center', padding: '14px 0' }}>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <strong style={{ color: '#e9edf5', fontSize: '0.95rem' }}>{prob.title}</strong>
                            <span
                              style={{
                                fontSize: '0.7rem',
                                padding: '2px 6px',
                                borderRadius: '3px',
                                textTransform: 'uppercase',
                                fontWeight: 600,
                                background:
                                  prob.difficulty.toLowerCase() === 'easy'
                                    ? 'rgba(103, 211, 145, 0.15)'
                                    : prob.difficulty.toLowerCase() === 'medium'
                                    ? 'rgba(242, 184, 75, 0.15)'
                                    : 'rgba(240, 162, 162, 0.15)',
                                color:
                                  prob.difficulty.toLowerCase() === 'easy'
                                    ? '#67d391'
                                    : prob.difficulty.toLowerCase() === 'medium'
                                    ? '#f2b84b'
                                    : '#f0a2a2',
                              }}
                            >
                              {prob.difficulty}
                            </span>
                          </div>
                          <div style={{ fontSize: '0.8rem', color: '#82909d', marginTop: '4px' }}>
                            Topic: {prob.topic} {prob.notes && `• ${prob.notes}`}
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                          {prob.is_solved ? (
                            <span
                              style={{
                                background: 'rgba(103, 211, 145, 0.15)',
                                color: '#67d391',
                                border: '1px solid rgba(103, 211, 145, 0.3)',
                                padding: '4px 10px',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                              }}
                            >
                              ✅ Solved {prob.solved_on ? `(${prob.solved_on})` : ''}
                            </span>
                          ) : (
                            <span
                              style={{
                                background: 'rgba(242, 184, 75, 0.15)',
                                color: '#f2b84b',
                                border: '1px solid rgba(242, 184, 75, 0.3)',
                                padding: '4px 10px',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                              }}
                            >
                              ⏳ Remaining
                            </span>
                          )}

                          {prob.leetcode_url && (
                            <a
                              href={prob.leetcode_url}
                              target="_blank"
                              rel="noreferrer"
                              className="secondary-button"
                              style={{ fontSize: '0.75rem', padding: '4px 8px', textDecoration: 'none' }}
                            >
                              LeetCode ↗
                            </a>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </div>
          ) : (
            <p className="empty-state">Select a job application above to view its DSA plan.</p>
          )}
        </div>
      )}
    </section>
  );
}