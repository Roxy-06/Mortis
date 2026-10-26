'use client';

import { useCallback, useEffect, useState } from 'react';

interface MemoryStats {
  episodes_total: number;
  resolved: number;
  unresolved: number;
  counterfactual: number;
  rolling: {
    n: number;
    win_rate: number | null;
    average_r: number | null;
    insufficient_history: boolean;
    minimum_n: number;
  };
  mode: string;
  last_restore_at_ms: number | null;
  last_catchup_at_ms: number | null;
  last_catchup_summary: {
    closed_positions?: number;
    resolved_samples?: number;
    resolved_counterfactuals?: number;
    unresolvable_samples?: number;
  };
  last_catchup_error: string | null;
  active_model_version: string | null;
  calibration_status: string;
  challenger_status: {
    version: string | null;
    status: string;
    reason: string;
  };
  retrain_check: {
    eligible?: boolean;
    new_resolved?: number;
    minimum_new?: number;
    resolved_total?: number;
    minimum_total?: number;
    reason?: string;
  };
}

function formatTime(value: number | null) {
  return value
    ? new Intl.DateTimeFormat('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: 'UTC',
      }).format(value)
    : 'Not recorded';
}

export function MemoryLearningCard() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const response = await fetch('/api/memory/stats', { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Memory status is unavailable.');
      setStats(payload as MemoryStats);
      setError('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Memory status is unavailable.');
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  return (
    <section className="rounded-3xl border border-[#1a2922] bg-[#111a16] p-5 sm:p-6">
      <div>
        <h2 className="text-sm font-semibold text-white">Persistent memory &amp; learning</h2>
        <p className="mt-1 text-xs text-[#7f9389]">
          Stored paper outcomes inform historical analogs; they do not guarantee an edge.
        </p>
      </div>
      {error && <p role="alert" className="mt-3 text-xs text-[#ff8c8c]">{error}</p>}
      {!stats && !error && <p className="mt-4 text-xs text-[#7f9389]">Loading memory status…</p>}
      {stats && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['Episodes', stats.episodes_total],
              ['Resolved', stats.resolved],
              ['Unresolved', stats.unresolved],
              ['Counterfactual', stats.counterfactual],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-[#18261f] bg-[#0c1310] p-3">
                <p className="text-[10px] uppercase tracking-wide text-[#7f9389]">{label}</p>
                <p className="mt-1 text-lg font-semibold text-white">{value}</p>
              </div>
            ))}
          </div>
          <div className="mt-3 grid gap-2 text-xs text-[#cbd5cf] sm:grid-cols-2">
            <p>Memory mode: <strong>{stats.mode}</strong></p>
            <p>Active model: <strong>{stats.active_model_version ?? 'none (rule fallback)'}</strong></p>
            <p>Calibration: <strong>{stats.calibration_status}</strong></p>
            <p>Last memory restore: <strong>{formatTime(stats.last_restore_at_ms)}</strong></p>
            <p>
              Challenger: <strong>{stats.challenger_status.status}</strong>
              {stats.challenger_status.version && ` · ${stats.challenger_status.version}`}
              {' '}— {stats.challenger_status.reason}
            </p>
            {stats.retrain_check?.reason && (
              <p>
                Daily retrain check: <strong>{stats.retrain_check.eligible ? 'eligible' : 'not eligible'}</strong>
                {' '}({stats.retrain_check.new_resolved ?? 0}/{stats.retrain_check.minimum_new ?? 50} new;
                {' '}{stats.retrain_check.resolved_total ?? 0}/{stats.retrain_check.minimum_total ?? 200} total)
              </p>
            )}
          </div>
          {stats.rolling.insufficient_history ? (
            <p className="mt-3 text-xs text-[#7f9389]">
              Insufficient history (n={stats.rolling.n}, need {stats.rolling.minimum_n}).
            </p>
          ) : (
            <p className="mt-3 text-xs text-[#cbd5cf]">
              Rolling win rate: {((stats.rolling.win_rate ?? 0) * 100).toFixed(1)}%
              {' '}and average {stats.rolling.average_r?.toFixed(2)}R
              {' '}(n={stats.rolling.n}).
            </p>
          )}
          {stats.last_catchup_error ? (
            <p role="alert" className="mt-3 rounded-lg bg-[#ff5c5c]/10 px-3 py-2 text-xs text-[#ffaaaa]">
              Catch-up needs attention: {stats.last_catchup_error}
            </p>
          ) : stats.last_catchup_summary && (
            (stats.last_catchup_summary.closed_positions ?? 0) > 0
            || (stats.last_catchup_summary.resolved_samples ?? 0) > 0
            || (stats.last_catchup_summary.resolved_counterfactuals ?? 0) > 0
          ) ? (
            <p className="mt-3 rounded-lg border border-[#263d32] bg-[#0c1310] px-3 py-2 text-xs text-[#7f9389]">
              While the app was off: closed {stats.last_catchup_summary.closed_positions ?? 0} position(s),
              {' '}resolved {stats.last_catchup_summary.resolved_samples ?? 0} linked sample(s) and
              {' '}{stats.last_catchup_summary.resolved_counterfactuals ?? 0} counterfactual(s);
              {' '}{stats.last_catchup_summary.unresolvable_samples ?? 0} remain explicitly unresolvable.
            </p>
          ) : (
            <p className="mt-3 text-xs text-[#7f9389]">
              Catch-up completed at {formatTime(stats.last_catchup_at_ms)}. No replayable outcome was newly resolved.
            </p>
          )}
        </>
      )}
    </section>
  );
}
