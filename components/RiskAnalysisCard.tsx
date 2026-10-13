'use client';

import { useState } from 'react';
import { 
  ShieldCheck, 
  RotateCcw, 
  TrendingUp, 
  TrendingDown, 
  Sliders, 
  Coins, 
  CheckCircle2 
} from 'lucide-react';

interface RiskAnalysisCardProps {
  initialCapital?: number;
  currentEquity?: number;
  totalTrades?: number;
  winRate?: number;
  onResetAccount?: () => void;
  onCalibrate?: (buyCutoff: number, sellCutoff: number) => void;
}

export function RiskAnalysisCard({
  initialCapital = 10000.00,
  currentEquity = 10340.50,
  totalTrades = 14,
  winRate = 71.4,
  onResetAccount,
  onCalibrate
}: RiskAnalysisCardProps) {
  const [buyCutoff, setBuyCutoff] = useState(0.60);
  const [sellCutoff, setSellCutoff] = useState(0.65);
  const [isCalibrated, setIsCalibrated] = useState(false);

  const profitLoss = currentEquity - initialCapital;
  const returnPct = ((profitLoss / initialCapital) * 100).toFixed(2);
  const isProfit = profitLoss >= 0;

  const handleCalibrate = () => {
    setIsCalibrated(true);
    setTimeout(() => setIsCalibrated(false), 2000);
    if (onCalibrate) {
      onCalibrate(buyCutoff, sellCutoff);
    }
  };

  return (
    <div className="bg-[#111a16] border border-[#1a2922] rounded-3xl p-4 sm:p-5 space-y-3.5 flex flex-col justify-between h-full">
      
      {/* Header */}
      <div className="flex items-center justify-between pb-0.5">
        <div className="flex items-center space-x-2">
          <div className="w-5 h-5 rounded-lg bg-[#b5f542]/15 flex items-center justify-center text-[#b5f542]">
            <ShieldCheck className="w-3.5 h-3.5" />
          </div>
          <h3 className="text-xs sm:text-sm font-semibold text-white truncate">
            Agent Risk & Threshold Engine
          </h3>
        </div>

        {/* Reset button */}
        <button
          onClick={onResetAccount}
          title="Reset to 10,000 artificial coins"
          className="flex items-center space-x-1 px-2 py-0.5 rounded-lg bg-[#0c1310] border border-[#18261f] hover:border-[#ff5c5c]/40 text-[#7f9389] hover:text-[#ff5c5c] text-[10px] font-medium transition-colors shrink-0"
        >
          <RotateCcw className="w-2.5 h-2.5" />
          <span>Reset $10k</span>
        </button>
      </div>

      {/* Asset Track Card */}
      <div className="bg-[#0c1310] p-3 rounded-2xl border border-[#18261f] space-y-1.5">
        <div className="flex justify-between items-center text-[11px]">
          <span className="text-[#7f9389] flex items-center gap-1">
            <Coins className="w-3 h-3 text-[#b5f542]" />
            Asset Capital Tracker
          </span>
          <span className="text-[10px] text-[#7f9389]">Base: ${initialCapital.toLocaleString()}</span>
        </div>

        <div className="flex items-baseline justify-between">
          <div className="text-xl sm:text-2xl font-bold font-sans text-white">
            ${currentEquity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className={`text-[11px] font-bold px-2 py-0.5 rounded-full flex items-center gap-0.5 ${
            isProfit ? 'bg-[#10b981]/15 text-[#10b981]' : 'bg-[#ff5c5c]/15 text-[#ff5c5c]'
          }`}>
            {isProfit ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
            {isProfit ? '+' : ''}{returnPct}%
          </div>
        </div>

        <div className="grid grid-cols-3 gap-1 pt-1 border-t border-[#18261f] text-center text-[9px]">
          <div>
            <span className="text-[#7f9389] block">WIN RATE</span>
            <span className="text-[#b5f542] font-bold text-[11px]">{winRate}%</span>
          </div>
          <div>
            <span className="text-[#7f9389] block">TRADES</span>
            <span className="text-white font-bold text-[11px]">{totalTrades} executed</span>
          </div>
          <div>
            <span className="text-[#7f9389] block">MAX DRAWDOWN</span>
            <span className="text-[#10b981] font-bold text-[11px]">-1.45%</span>
          </div>
        </div>
      </div>

      {/* Dual Threshold Frequency Controls (Buy & Sell) */}
      <div className="space-y-2">
        <span className="text-[10px] font-semibold text-white block">
          Dual Threshold Frequencies (Active Filter)
        </span>

        {/* Buy Threshold */}
        <div className="bg-[#0c1310] p-2 rounded-xl border border-[#18261f] space-y-1">
          <div className="flex justify-between items-center text-[11px]">
            <span className="text-[#10b981] font-medium flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[#10b981]"></span>
              Buy Frequency
            </span>
            <span className="text-white font-mono font-bold text-[11px]">{buyCutoff.toFixed(2)} (4.2 Hz)</span>
          </div>
          <input 
            type="range"
            min="0.40"
            max="0.85"
            step="0.05"
            value={buyCutoff}
            onChange={(e) => setBuyCutoff(parseFloat(e.target.value))}
            className="w-full accent-[#10b981] h-1 bg-[#18261f] rounded-lg cursor-pointer"
          />
        </div>

        {/* Sell Threshold */}
        <div className="bg-[#0c1310] p-2 rounded-xl border border-[#18261f] space-y-1">
          <div className="flex justify-between items-center text-[11px]">
            <span className="text-[#ff5c5c] font-medium flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[#ff5c5c]"></span>
              Sell Frequency
            </span>
            <span className="text-white font-mono font-bold text-[11px]">{sellCutoff.toFixed(2)} (3.8 Hz)</span>
          </div>
          <input 
            type="range"
            min="0.45"
            max="0.90"
            step="0.05"
            value={sellCutoff}
            onChange={(e) => setSellCutoff(parseFloat(e.target.value))}
            className="w-full accent-[#ff5c5c] h-1 bg-[#18261f] rounded-lg cursor-pointer"
          />
        </div>
      </div>

      {/* Calibrate Trigger Button */}
      <button
        onClick={handleCalibrate}
        className="w-full py-2 rounded-xl bg-[#b5f542] hover:bg-[#c5fb5a] text-[#080d0b] text-xs font-bold transition-all flex items-center justify-center space-x-1.5 shadow"
      >
        {isCalibrated ? (
          <>
            <CheckCircle2 className="w-3 h-3" />
            <span>Calibrated!</span>
          </>
        ) : (
          <>
            <Sliders className="w-3 h-3" />
            <span>Calibrate Agent Parameters</span>
          </>
        )}
      </button>

    </div>
  );
}
