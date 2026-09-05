import { useState, useEffect } from 'react';
import { api, type MorningBriefingResponse } from '../api/client';

type Props = {
  isOpen: boolean;
  onClose: () => void;
};

export default function BriefingModal({ isOpen, onClose }: Props) {
  const [loading, setLoading] = useState(false);
  const [briefingData, setBriefingData] = useState<MorningBriefingResponse | null>(null);
  const [sendTelegram, setSendTelegram] = useState(false);
  const [telegramStatus, setTelegramStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function fetchBriefing(sendNotification = false) {
    setLoading(true);
    setError(null);
    try {
      const response = await api.generateBriefing(sendNotification);
      setBriefingData(response);
      if (sendNotification) {
        setTelegramStatus(
          response.mocked_delivery
            ? '✓ Mock Telegram notification delivered'
            : '✓ Telegram message sent'
        );
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to generate morning briefing.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchBriefing(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-card" style={{ maxWidth: '700px' }}>
        <div className="modal-header">
          <div>
            <p className="eyebrow">Daily Executive Summary</p>
            <h2>🌅 Morning Briefing</h2>
          </div>
          <button className="btn-close" onClick={onClose} aria-label="Close modal">×</button>
        </div>

        {loading && <div className="notice">Synthesizing your daily rhythm with Gemini AI...</div>}
        {error && <div className="notice error">{error}</div>}

        {briefingData && !loading && (
          <div style={{ display: 'grid', gap: '1rem', marginTop: '0.5rem' }}>
            <div style={{ padding: '1rem', background: 'rgba(242, 184, 75, 0.08)', borderLeft: '3px solid #f2b84b', borderRadius: '4px' }}>
              <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1.15rem' }}>{briefingData.briefing.greeting}</h3>
              {briefingData.briefing.quote_or_motto && (
                <p style={{ margin: 0, fontStyle: 'italic', color: '#f2b84b', fontSize: '0.9rem' }}>
                  &ldquo;{briefingData.briefing.quote_or_motto}&rdquo;
                </p>
              )}
            </div>

            <div className="briefing-section">
              <h4 style={{ margin: '0 0 0.5rem 0', color: '#e9edf5', fontSize: '0.95rem' }}>🎯 Top Priorities Today</h4>
              <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                {briefingData.briefing.top_priorities.map((priority, i) => (
                  <li key={i} style={{ marginBottom: '0.35rem', color: '#e2e8ee' }}>{priority}</li>
                ))}
              </ul>
            </div>

            <div className="briefing-section">
              <h4 style={{ margin: '0 0 0.5rem 0', color: '#e9edf5', fontSize: '0.95rem' }}>📅 Today&apos;s Rhythm</h4>
              <p style={{ margin: 0, color: 'var(--text-muted, #9ba8b5)', fontSize: '0.9rem', lineHeight: '1.4' }}>
                {briefingData.briefing.schedule_overview}
              </p>
            </div>

            {briefingData.briefing.urgent_alerts && briefingData.briefing.urgent_alerts.length > 0 && (
              <div style={{ padding: '0.75rem', background: 'rgba(247, 118, 142, 0.1)', border: '1px solid rgba(247, 118, 142, 0.3)', borderRadius: '4px' }}>
                <h4 style={{ margin: '0 0 0.25rem 0', color: '#f7768e', fontSize: '0.9rem' }}>⚠️ Upcoming Cutoffs (&lt;48h)</h4>
                <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.85rem' }}>
                  {briefingData.briefing.urgent_alerts.map((alert, i) => (
                    <li key={i} style={{ color: '#f0a2a2' }}>{alert}</li>
                  ))}
                </ul>
              </div>
            )}

            {briefingData.briefing.recommended_recovery_action && (
              <div style={{ padding: '0.75rem', background: 'rgba(103, 211, 145, 0.1)', border: '1px solid rgba(103, 211, 145, 0.3)', borderRadius: '4px' }}>
                <strong style={{ color: '#67d391', fontSize: '0.85rem' }}>🛠️ Pro-tip / Daily Recovery:</strong>
                <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.85rem', color: '#e2e8ee' }}>
                  {briefingData.briefing.recommended_recovery_action}
                </p>
              </div>
            )}

            {telegramStatus && (
              <div style={{ fontSize: '0.85rem', color: '#67d391' }}>{telegramStatus}</div>
            )}
          </div>
        )}

        <div className="modal-actions" style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.85rem', color: '#a9b5c0' }}>
            <input
              type="checkbox"
              checked={sendTelegram}
              onChange={(e) => setSendTelegram(e.target.checked)}
            />
            Dispatch notification via Telegram
          </label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => fetchBriefing(sendTelegram)}
              disabled={loading}
            >
              🔄 Refresh Briefing
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={onClose}
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
