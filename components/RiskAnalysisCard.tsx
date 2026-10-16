'use client';

import { RotateCcw, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react';

interface RiskAnalysisCardProps {
  initialCapital?: number;
  currentEquity?: number;
  totalTrades?: number;
  winRate?: number;
  maxDrawdownPct?: number;
  todayRealizedPnl?: number;
  onResetAccount?: () => void;
}

export function RiskAnalysisCard({
  initialCapital = 10000,
  currentEquity = 10000,
  totalTrades = 0,
  winRate = 0,
  maxDrawdownPct = 0,
  todayRealizedPnl = 0,
  onResetAccount,
}: RiskAnalysisCardProps) {
  const profitLoss = currentEquity - initialCapital;
  const returnPct = initialCapital > 0 ? (profitLoss / initialCapital) * 100 : 0;
  const isProfit = profitLoss >= 0;

  return (
    <div className="flex h-full flex-col justify-between space-y-4 rounded-3xl border border-[#1a2922] bg-[#111a16] p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex h-5 w-5 items-center justify-center rounded-lg bg-[#b5f542]/15 text-[#b5f542]">
            <ShieldCheck className="h-3.5 w-3.5" />
          </div>
          <h3 className="truncate text-xs font-semibold text-white sm:text-sm">
            Paper account &amp; risk
          </h3>
        </div>
        <button
          type="button"
          onClick={onResetAccount}
          title="Reset the paper account to its starting balance"
          className="flex shrink-0 items-center gap-1 rounded-lg border border-[#18261f] bg-[#0c1310] px-2 py-1 text-[10px] font-medium text-[#7f9389] transition-colors hover:border-[#ff5c5c]/40 hover:text-[#ff5c5c]"
        >
          <RotateCcw className="h-2.5 w-2.5" />
          Reset
        </button>
      </div>

      <div className="space-y-3 rounded-2xl border border-[#18261f] bg-[#0c1310] p-3">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-[#7f9389]">Simulated USDT equity</span>
          <span className="text-[10px] text-[#7f9389]">Start ${initialCapital.toLocaleString()}</span>
        </div>
        <div className="flex items-baseline justify-between">
          <div className="text-xl font-bold text-white sm:text-2xl">
            ${currentEquity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className={`flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11px] font-bold ${
            isProfit ? 'bg-[#10b981]/15 text-[#10b981]' : 'bg-[#ff5c5c]/15 text-[#ff5c5c]'
          }`}>
            {isProfit ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}
            {isProfit ? '+' : ''}{returnPct.toFixed(2)}%
          </div>
        </div>
        <div className="grid grid-cols-3 gap-1 border-t border-[#18261f] pt-2 text-center text-[9px]">
          <div>
            <span className="block text-[#7f9389]">CLOSED</span>
            <span className="text-[11px] font-bold text-white">{totalTrades}</span>
          </div>
          <div>
            <span className="block text-[#7f9389]">WIN RATE</span>
            <span className="text-[11px] font-bold text-[#b5f542]">{winRate.toFixed(1)}%</span>
          </div>
          <div>
            <span className="block text-[#7f9389]">MAX DRAWDOWN</span>
            <span className="text-[11px] font-bold text-[#ff8c8c]">-{maxDrawdownPct.toFixed(2)}%</span>
          </div>
        </div>
        <div className="flex justify-between border-t border-[#18261f] pt-2 text-[10px]">
          <span className="text-[#7f9389]">Realized P&amp;L today (UTC)</span>
          <span className={todayRealizedPnl >= 0 ? 'text-[#10b981]' : 'text-[#ff8c8c]'}>
            {todayRealizedPnl >= 0 ? '+' : ''}${todayRealizedPnl.toFixed(2)}
          </span>
        </div>
      </div>

      <div className="space-y-2 rounded-2xl border border-[#18261f] bg-[#0c1310] p-3 text-[10px]">
        <div className="flex justify-between gap-2">
          <span className="text-[#7f9389]">Mode</span>
          <span className="font-semibold text-[#b5f542]">Paper only · no exchange orders</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-[#7f9389]">Leverage ceiling</span>
          <span className="text-white">10x isolated margin</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-[#7f9389]">Round-trip fee</span>
          <span className="text-white">3% of entry notional</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-[#7f9389]">Daily loss stop</span>
          <span className="text-white">3% of starting equity</span>
        </div>
      </div>
    </div>
  );
}
