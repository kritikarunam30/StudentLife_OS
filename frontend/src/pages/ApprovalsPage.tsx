import { useState } from 'react';
import { api, type Approval } from '../api/client';

export default function ApprovalsPage({ approvals, onChanged }: { approvals: Approval[]; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  async function resolve(id: number, action: 'approve' | 'reject') {
    try { if (action === 'approve') await api.approve(id); else await api.reject(id); await onChanged(); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Unable to update approval.'); }
  }
  return <section><div className="section-heading"><div><p className="eyebrow">Human control</p><h2>Approvals</h2></div><span className="muted">{approvals.filter((item) => item.status === 'pending').length} pending</span></div>{error && <div className="notice error">{error}</div>}<div className="task-list">{approvals.length ? approvals.map((item) => <article className="task-row" key={item.id}><div><strong>{item.action_type}</strong><p className="muted">{item.description}</p></div>{item.status === 'pending' ? <div style={{ display: 'flex', gap: 8 }}><button className="primary-button" onClick={() => resolve(item.id, 'approve')}>Approve</button><button className="secondary-button" onClick={() => resolve(item.id, 'reject')}>Reject</button></div> : <span className="task-status">{item.status}</span>}</article>) : <p className="empty-state">Nothing waiting for approval.</p>}</div></section>;
}