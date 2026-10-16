'use client';

import { useState } from 'react';
import { ArrowDownRight, ArrowUpRight, X } from 'lucide-react';

export interface OpenPosition {
  side: 'long' | 'short';
  entry: number;
  size: number;
  leverage: number;
  margin: number;
  source: string;
  opened_at: number;
  unrealized_pnl_usd?: number;
}

interface ManualTradePanelProps {
  availableBalance: number;
  currentPrice: number;
  openPosition: OpenPosition | null;
  onAccountChanged: () => void;
}

export function ManualTradePanel({
  availableBalance,
  currentPrice,
  openPosition,
  onAccountChanged,
}: ManualTradePanelProps) {
  const [side, setSide] = useState<'long' | 'short'>('long');
  const [margin, setMargin] = useState('100');
  const [leverage, setLeverage] = useState('1');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const execute = async (path: string, body?: object) => {
    setBusy(true);
    setMessage('');
    setError('');
    try {
      const response = await fetch(path, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'The paper-trading request failed.');
      }
      if (result.trade?.pnl_usd !== undefined) {
        setMessage(
          `Position closed: ${result.trade.pnl_usd >= 0 ? '+' : ''}$${result.trade.pnl_usd.toFixed(2)} net after fees.`,
        );
      } else {
        setMessage('Simulated position opened. No real order was sent.');
      }
      onAccountChanged();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The request failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-3xl border border-[#1a2922] bg-[#111a16] p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-white">Manual paper trade</h2>
          <p className="mt-1 text-xs text-[#7f9389]">
            Simulated BTC/USDT only · 0.1% round-trip fee · choose 1x–200x
          </p>
        </div>
        <div className="text-right text-xs text-[#7f9389]">
          <span className="block">Live reference price</span>
          <strong className="text-sm text-white">
            {currentPrice > 0
              ? `$${currentPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
              : 'Unavailable'}
          </strong>
        </div>
      </div>

      {openPosition ? (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#263d32] bg-[#0c1310] p-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              {openPosition.side === 'long' ? (
                <ArrowUpRight className="h-4 w-4 text-[#10b981]" />
              ) : (
                <ArrowDownRight className="h-4 w-4 text-[#ff5c5c]" />
              )}
              {openPosition.side.toUpperCase()} · {openPosition.leverage}x
              <span className="text-xs font-normal text-[#7f9389]">
                ({openPosition.source})
              </span>
            </div>
            <p className="mt-1 text-xs text-[#7f9389]">
              Entry ${openPosition.entry.toLocaleString()} · {openPosition.size} BTC ·
              ${openPosition.margin.toFixed(2)} margin
            </p>
            <p className="mt-1 text-xs text-[#7f9389]">
              Estimated unrealized P&amp;L after fee:{' '}
              <span className={(openPosition.unrealized_pnl_usd ?? 0) >= 0 ? 'text-[#10b981]' : 'text-[#ff5c5c]'}>
                ${openPosition.unrealized_pnl_usd?.toFixed(2) ?? '0.00'}
              </span>
            </p>
          </div>
          <button
            type="button"
            disabled={busy || currentPrice <= 0}
            onClick={() => execute('/api/trades/close')}
            className="inline-flex items-center gap-2 rounded-xl border border-[#ff5c5c]/40 px-4 py-2 text-xs font-bold text-[#ff8c8c] transition hover:bg-[#ff5c5c]/10 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <X className="h-3.5 w-3.5" />
            {busy ? 'Closing…' : 'Close position'}
          </button>
        </div>
      ) : (
        <form
          className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 lg:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault();
            void execute('/api/trades', {
              side,
              margin_usd: Number(margin),
              leverage: Number(leverage),
            });
          }}
        >
          <label className="space-y-1 text-xs text-[#7f9389]">
            <span>Direction</span>
            <select
              value={side}
              onChange={(event) => setSide(event.target.value as 'long' | 'short')}
              className="w-full rounded-xl border border-[#1a2922] bg-[#0c1310] px-3 py-2.5 text-sm text-white"
            >
              <option value="long">Buy / Long</option>
              <option value="short">Sell / Short</option>
            </select>
          </label>
          <label className="space-y-1 text-xs text-[#7f9389]">
            <span>Margin (USDT)</span>
            <input
              type="number"
              min="1"
              max={Math.max(1, availableBalance)}
              step="1"
              required
              value={margin}
              onChange={(event) => setMargin(event.target.value)}
              className="w-full rounded-xl border border-[#1a2922] bg-[#0c1310] px-3 py-2.5 text-sm text-white"
            />
            <span className="block">Available: ${availableBalance.toFixed(2)}</span>
          </label>
          <label className="space-y-1 text-xs text-[#7f9389]">
            <span>Leverage</span>
            <select
              value={leverage}
              onChange={(event) => setLeverage(event.target.value)}
              className="w-full rounded-xl border border-[#1a2922] bg-[#0c1310] px-3 py-2.5 text-sm text-white"
            >
              {[1, 5, 10, 20, 100, 200].map((value) => (
                <option key={value} value={value}>{value}x</option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={busy || currentPrice <= 0 || availableBalance <= 0}
            className={`rounded-xl px-4 py-2.5 text-sm font-bold text-black transition disabled:cursor-not-allowed disabled:opacity-40 ${
              side === 'long' ? 'bg-[#b5f542] hover:bg-[#c5fb5a]' : 'bg-[#ff8c8c] hover:bg-[#ffa6a6]'
            }`}
          >
            {busy ? 'Submitting…' : side === 'long' ? 'Buy BTC (paper)' : 'Sell BTC (paper)'}
          </button>
        </form>
      )}

      {message && <p role="status" className="mt-3 text-xs text-[#10b981]">{message}</p>}
      {error && <p role="alert" className="mt-3 text-xs text-[#ff8c8c]">{error}</p>}
    </section>
  );
}
