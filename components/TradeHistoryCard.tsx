'use client';

import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';

interface Trade {
  id: string;
  side: 'long' | 'short';
  entry: number;
  size: number;
  notional: number;
  leverage: number;
  margin: number;
  stop_loss: number | null;
  take_profit: number | null;
  opened_at: number;
  closed_at: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  pnl_usd: number | null;
  r_multiple: number | null;
  bars_held: number;
  source: string;
  rationale: string | null;
  status: 'open' | 'closed';
}

interface TradePage {
  trades: Trade[];
  total: number;
  current_price: number;
}

interface TradeDetail extends Trade {
  decision?: {
    decision_id: string;
    direction: string;
    source: string;
    features: Record<string, number>;
    memory: {
      n?: number;
      shrunk_win_rate?: number | null;
      average_r?: number | null;
      neighbors?: Array<{
        id: string;
        outcome: string;
        r_multiple: number | null;
        distance: number;
      }>;
    };
  } | null;
  memory_episode?: {
    lesson_text: string | null;
    lesson_source: string | null;
    feature_vector: Record<string, number>;
  };
  events?: Array<{ event_type: string; created_at_ms: number }>;
}

const PAGE_SIZE = 25;
const REFRESH_INTERVAL_MS = 15_000;

function formatPrice(price: number | null) {
  return price === null
    ? '—'
    : `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatTimestamp(timestamp: number | null) {
  if (timestamp === null) return '—';
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'medium',
    timeZone: 'UTC',
  }).format(timestamp);
}

export function TradeHistoryCard() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [currentPrice, setCurrentPrice] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [selectedTrade, setSelectedTrade] = useState<TradeDetail | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`/api/trades?limit=${PAGE_SIZE}&offset=0`, {
        cache: 'no-store',
      });
      const data: TradePage & { detail?: string } = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Trade history could not be loaded.');
      }
      setTrades((previous) => {
        const newestIds = new Set(data.trades.map((trade) => trade.id));
        const olderTrades = previous.filter((trade) => !newestIds.has(trade.id));
        return [...data.trades, ...olderTrades];
      });
      setCurrentPrice(data.current_price);
      setTotal(data.total);
      setError('');
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Trade history could not be loaded.',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const loadOlderTrades = async () => {
    setLoadingMore(true);
    try {
      const response = await fetch(
        `/api/trades?limit=${PAGE_SIZE}&offset=${trades.length}`,
        { cache: 'no-store' },
      );
      const data: TradePage & { detail?: string } = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Older trade history could not be loaded.');
      }
      setTrades((previous) => {
        const knownIds = new Set(previous.map((trade) => trade.id));
        return [...previous, ...data.trades.filter((trade) => !knownIds.has(trade.id))];
      });
      setCurrentPrice(data.current_price);
      setTotal(data.total);
      setError('');
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Older trade history could not be loaded.',
      );
    } finally {
      setLoadingMore(false);
    }
  };

  const showDetails = async (tradeId: string) => {
    try {
      const response = await fetch(`/api/trades/${encodeURIComponent(tradeId)}`, {
        cache: 'no-store',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Trade details could not be loaded.');
      setSelectedTrade(data.trade as TradeDetail);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Trade details could not be loaded.');
    }
  };

  return (
    <section className="rounded-3xl border border-[#1a2922] bg-[#111a16] p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-white">Trade history</h2>
          <p className="mt-1 text-xs text-[#7f9389]">
            Entries, exits, net realized P&amp;L after fees, and execution source · timestamps UTC
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-[#263d32] bg-[#0c1310] px-3 py-2 text-xs font-medium text-[#cbd5cf] hover:text-white disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <p role="alert" className="mb-3 rounded-xl border border-[#ff5c5c]/30 bg-[#ff5c5c]/10 px-3 py-2 text-xs text-[#ffaaaa]">
          {error}
        </p>
      )}

      <div className="overflow-x-auto rounded-2xl border border-[#18261f]">
        <table className="min-w-[1180px] w-full text-left text-xs">
          <thead className="bg-[#0c1310] text-[10px] uppercase tracking-wide text-[#7f9389]">
            <tr>
              <th className="px-3 py-3 font-medium">Opened / closed (UTC)</th>
              <th className="px-3 py-3 font-medium">Position</th>
              <th className="px-3 py-3 font-medium">Source</th>
              <th className="px-3 py-3 text-right font-medium">Entry</th>
              <th className="px-3 py-3 text-right font-medium">Stop / target</th>
              <th className="px-3 py-3 text-right font-medium">Exit / mark</th>
              <th className="px-3 py-3 text-right font-medium">Net P&amp;L</th>
              <th className="px-3 py-3 text-right font-medium">R / bars</th>
              <th className="px-3 py-3 font-medium">Status / close reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#18261f]">
            {trades.map((trade) => {
              const openPnl = trade.side === 'long'
                ? (currentPrice - trade.entry) * trade.size
                : (trade.entry - currentPrice) * trade.size;
              const pnl = trade.status === 'open'
                ? Math.max(openPnl - trade.notional * 0.001, -trade.margin)
                : trade.pnl_usd;
              const isProfit = (pnl ?? 0) >= 0;

              return (
                <tr key={trade.id} className="bg-[#111a16] hover:bg-[#142019]">
                  <td className="whitespace-nowrap px-3 py-3 text-[#cbd5cf]">
                    <span className="block">{formatTimestamp(trade.opened_at)}</span>
                    {trade.closed_at !== null && (
                      <span className="mt-1 block text-[10px] text-[#7f9389]">
                        Closed {formatTimestamp(trade.closed_at)}
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3">
                    <span className={`font-semibold ${trade.side === 'long' ? 'text-[#10b981]' : 'text-[#ff8c8c]'}`}>
                      {trade.side === 'long' ? 'LONG / BUY' : 'SHORT / SELL'}
                    </span>
                    <span className="ml-2 text-[#7f9389]">· {trade.leverage}x</span>
                  </td>
                  <td className="px-3 py-3 text-[#cbd5cf]">
                    {trade.source === 'manual' ? 'Manual' : 'AI agent'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-white">
                    {formatPrice(trade.entry)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-mono">
                    <span className="text-[#ff8c8c]">{formatPrice(trade.stop_loss)}</span>
                    <span className="mx-1 text-[#7f9389]">/</span>
                    <span className="text-[#10b981]">{formatPrice(trade.take_profit)}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-white">
                    {formatPrice(trade.status === 'open' ? currentPrice : trade.exit_price)}
                    {trade.status === 'open' && (
                      <span className="ml-1 text-[10px] text-[#7f9389]">· mark</span>
                    )}
                  </td>
                  <td className={`whitespace-nowrap px-3 py-3 text-right font-mono font-semibold ${
                    isProfit ? 'text-[#10b981]' : 'text-[#ff8c8c]'
                  }`}>
                    {pnl === null
                      ? '—'
                      : `${pnl >= 0 ? '+' : '-'}$${Math.abs(pnl).toFixed(2)}`}
                    {trade.status === 'open' && <span className="ml-1 text-[10px] font-normal">est.</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-[#cbd5cf]">
                    {trade.r_multiple === null ? '—' : `${trade.r_multiple.toFixed(2)}R`}
                    <span className="ml-1 text-[10px] text-[#7f9389]">/ {trade.bars_held}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-[#cbd5cf]">
                    <span className={trade.status === 'open' ? 'text-[#b5f542]' : 'text-[#7f9389]'}>
                      {trade.status === 'open' ? 'OPEN' : 'CLOSED'}
                    </span>
                    {trade.exit_reason && <span className="ml-2 text-[#7f9389]">· {trade.exit_reason}</span>}
                    <button
                      type="button"
                      className="ml-2 text-[#b5f542] underline"
                      onClick={() => void showDetails(trade.id)}
                    >
                      Details
                    </button>
                  </td>
                </tr>
              );
            })}
            {!loading && trades.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-10 text-center text-[#7f9389]">
                  No trades recorded yet. Agent decisions that result in no trade are not executions.
                </td>
              </tr>
            )}
            {loading && trades.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-10 text-center text-[#7f9389]">
                  Loading trade history…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selectedTrade && (
        <section className="mt-4 rounded-2xl border border-[#263d32] bg-[#0c1310] p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-white">Trade decision and memory details</h3>
            <button
              type="button"
              className="text-xs text-[#7f9389] hover:text-white"
              onClick={() => setSelectedTrade(null)}
            >
              Close
            </button>
          </div>
          <div className="mt-3 grid gap-4 text-xs sm:grid-cols-2">
            <div>
              <h4 className="font-semibold text-[#cbd5cf]">Decision features</h4>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[10px] text-[#7f9389]">
                {JSON.stringify(selectedTrade.decision?.features ?? {}, null, 2)}
              </pre>
            </div>
            <div>
              <h4 className="font-semibold text-[#cbd5cf]">Retrieved historical analogs</h4>
              {selectedTrade.decision?.memory ? (
                <>
                  <p className="mt-2 text-[#7f9389]">
                    n={selectedTrade.decision.memory.n ?? 0} · shrunk win rate{' '}
                    {selectedTrade.decision.memory.shrunk_win_rate == null
                      ? 'insufficient history'
                      : `${(selectedTrade.decision.memory.shrunk_win_rate * 100).toFixed(1)}%`}
                    {' '}· average R {selectedTrade.decision.memory.average_r?.toFixed(2) ?? '—'}
                  </p>
                  <ul className="mt-2 space-y-1 text-[#7f9389]">
                    {(selectedTrade.decision.memory.neighbors ?? []).slice(0, 5).map((neighbor) => (
                      <li key={neighbor.id}>
                        {neighbor.outcome} · {neighbor.r_multiple?.toFixed(2) ?? '—'}R ·
                        {' '}distance {neighbor.distance.toFixed(3)}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="mt-2 text-[#7f9389]">No stored decision analogs.</p>
              )}
            </div>
          </div>
          <div className="mt-3 rounded-xl border border-[#18261f] bg-[#111a16] p-3">
            <h4 className="font-semibold text-[#cbd5cf]">Lesson hypothesis</h4>
            <p className="mt-1 text-xs text-[#7f9389]">
              {selectedTrade.memory_episode?.lesson_text ?? 'No lesson recorded for this trade.'}
            </p>
            <p className="mt-1 text-[10px] text-[#7f9389]">
              Stored lessons are hypotheses, not causal conclusions.
            </p>
          </div>
        </section>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-[#7f9389]">
        <span>Showing {trades.length} of {total} trades · estimated open P&amp;L is not realized</span>
        {trades.length < total && (
          <button
            type="button"
            onClick={() => void loadOlderTrades()}
            disabled={loadingMore}
            className="rounded-xl border border-[#263d32] px-3 py-2 font-medium text-white hover:bg-[#18261f] disabled:opacity-50"
          >
            {loadingMore ? 'Loading…' : 'Load older trades'}
          </button>
        )}
      </div>
    </section>
  );
}
