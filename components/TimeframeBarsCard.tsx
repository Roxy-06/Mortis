'use client';

import { useState } from 'react';
import { BarChart3, TrendingUp, TrendingDown, Layers, Activity } from 'lucide-react';

interface TimeframeMetric {
  tf: string;
  label: string;
  score: number;
  bias: 'BULLISH' | 'NEUTRAL' | 'BEARISH';
  rsi: number;
  emaStatus: string;
  volumeRatio: string;
}

export function TimeframeBarsCard() {
  const [selectedTf, setSelectedTf] = useState<string>('1h');

  const metrics: TimeframeMetric[] = [
    { tf: '15m', label: 'Micro Momentum', score: 86, bias: 'BULLISH', rsi: 58.4, emaStatus: 'EMA20 > EMA50', volumeRatio: '1.82x' },
    { tf: '1h', label: 'Structural Trend', score: 74, bias: 'BULLISH', rsi: 52.8, emaStatus: 'EMA50 Expanding', volumeRatio: '1.34x' },
    { tf: '4h', label: 'Macro Regime', score: 58, bias: 'NEUTRAL', rsi: 44.2, emaStatus: 'Testing S/R Base', volumeRatio: '1.15x' },
    { tf: '1D', label: 'Daily Confluence', score: 68, bias: 'BULLISH', rsi: 51.0, emaStatus: 'Above 200 EMA', volumeRatio: '1.20x' },
  ];

  const activeMetric = metrics.find(m => m.tf === selectedTf) || metrics[1];

  return (
    <div className="bg-[#111a16] border border-[#1a2922] rounded-3xl p-5 sm:p-6 space-y-4 flex flex-col justify-between">
      
      {/* Header */}
      <div className="flex items-center justify-between pb-1">
        <div className="flex items-center space-x-2">
          <div className="w-6 h-6 rounded-lg bg-[#b5f542]/15 flex items-center justify-center text-[#b5f542]">
            <BarChart3 className="w-3.5 h-3.5" />
          </div>
          <h3 className="text-sm font-semibold text-white">
            Timeframe Confluence Bars
          </h3>
        </div>

        {/* Timeframe pill tabs */}
        <div className="flex items-center bg-[#0c1310] p-1 rounded-xl border border-[#1a2922]">
          {metrics.map((m) => (
            <button
              key={m.tf}
              onClick={() => setSelectedTf(m.tf)}
              className={`px-2 py-0.5 rounded-lg text-[10px] font-bold transition-all ${
                selectedTf === m.tf
                  ? 'bg-[#b5f542] text-black shadow-sm'
                  : 'text-[#7f9389] hover:text-white'
              }`}
            >
              {m.tf}
            </button>
          ))}
        </div>
      </div>

      {/* Bar Graphs Display */}
      <div className="space-y-3">
        {metrics.map((m) => {
          const isSelected = selectedTf === m.tf;
          const isBull = m.score >= 65;
          const isNeutral = m.score >= 45 && m.score < 65;

          return (
            <div 
              key={m.tf}
              onClick={() => setSelectedTf(m.tf)}
              className={`p-2 rounded-xl transition-all cursor-pointer ${
                isSelected ? 'bg-[#18261f] border border-[#263d32]' : 'hover:bg-[#16231d]'
              }`}
            >
              <div className="flex justify-between items-center text-xs mb-1.5">
                <div className="flex items-center space-x-2">
                  <span className="font-bold text-white font-mono">{m.tf}</span>
                  <span className="text-[11px] text-[#7f9389]">{m.label}</span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                    isBull ? 'text-[#10b981] bg-[#10b981]/10' :
                    isNeutral ? 'text-[#b5f542] bg-[#b5f542]/10' :
                    'text-[#ff5c5c] bg-[#ff5c5c]/10'
                  }`}>
                    {m.bias}
                  </span>
                  <span className="font-bold text-white text-xs font-mono">{m.score}%</span>
                </div>
              </div>

              {/* Progress Bar */}
              <div className="w-full h-2.5 bg-[#0c1310] rounded-full overflow-hidden border border-[#18261f]">
                <div 
                  className={`h-full rounded-full transition-all duration-500 ${
                    isBull ? 'bg-gradient-to-r from-[#10b981] to-[#b5f542]' :
                    isNeutral ? 'bg-gradient-to-r from-[#7f9389] to-[#b5f542]' :
                    'bg-[#ff5c5c]'
                  }`}
                  style={{ width: `${m.score}%` }}
                ></div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected Timeframe Breakdown Row */}
      <div className="pt-2 border-t border-[#18261f] grid grid-cols-3 gap-2 text-center text-xs">
        <div className="bg-[#0c1310] p-2 rounded-xl border border-[#18261f]">
          <span className="text-[10px] text-[#7f9389] block">RSI (14)</span>
          <span className="text-white font-bold font-mono">{activeMetric.rsi}</span>
        </div>
        <div className="bg-[#0c1310] p-2 rounded-xl border border-[#18261f]">
          <span className="text-[10px] text-[#7f9389] block">EMA RIBBON</span>
          <span className="text-[#b5f542] font-semibold text-[10px] truncate block">{activeMetric.emaStatus}</span>
        </div>
        <div className="bg-[#0c1310] p-2 rounded-xl border border-[#18261f]">
          <span className="text-[10px] text-[#7f9389] block">VOL DELTA</span>
          <span className="text-[#10b981] font-bold font-mono">{activeMetric.volumeRatio}</span>
        </div>
      </div>

    </div>
  );
}
