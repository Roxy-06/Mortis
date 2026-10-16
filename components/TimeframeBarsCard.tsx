'use client';

import { useState } from 'react';
import { BarChart3 } from 'lucide-react';

export interface TimeframeIndicators {
  rsi14: number;
  ema20: number;
  ema50: number;
  ema200: number;
  volume_ratio: number;
  trend_flags: {
    price_above_ema50: boolean;
    ema20_above_ema50: boolean;
    ema50_above_ema200: boolean;
  };
  macd: { histogram_rising: boolean };
}

interface TimeframeMetric {
  tf: string;
  label: string;
  score: number;
  bias: 'BULLISH' | 'NEUTRAL' | 'BEARISH';
  rsi: number;
  emaStatus: string;
  volumeRatio: number;
}

interface TimeframeBarsCardProps {
  timeframes?: Record<string, TimeframeIndicators>;
}

const timeframeLabels: Record<string, string> = {
  '15m': 'Entry momentum',
  '1h': 'Market structure',
  '4h': 'Macro trend',
};

export function TimeframeBarsCard({ timeframes = {} }: TimeframeBarsCardProps) {
  const [selectedTf, setSelectedTf] = useState('1h');
  const metrics: TimeframeMetric[] = ['15m', '1h', '4h'].flatMap((tf) => {
    const indicators = timeframes[tf];
    if (!indicators) return [];
    const flags = indicators.trend_flags;
    const bullishSignals = [
      flags.price_above_ema50,
      flags.ema20_above_ema50,
      flags.ema50_above_ema200,
      indicators.macd.histogram_rising,
      indicators.rsi14 >= 50,
    ].filter(Boolean).length;
    const bearishSignals = [
      !flags.price_above_ema50,
      !flags.ema20_above_ema50,
      !flags.ema50_above_ema200,
      !indicators.macd.histogram_rising,
      indicators.rsi14 < 50,
    ].filter(Boolean).length;
    const bias =
      bullishSignals > bearishSignals
        ? 'BULLISH'
        : bearishSignals > bullishSignals
          ? 'BEARISH'
          : 'NEUTRAL';

    return [{
      tf,
      label: timeframeLabels[tf],
      score: Math.round((Math.max(bullishSignals, bearishSignals) / 5) * 100),
      bias,
      rsi: indicators.rsi14,
      emaStatus: `20 ${indicators.ema20 >= indicators.ema50 ? '>' : '<'} 50 · 50 ${indicators.ema50 >= indicators.ema200 ? '>' : '<'} 200`,
      volumeRatio: indicators.volume_ratio,
    }];
  });
  const activeMetric = metrics.find((metric) => metric.tf === selectedTf) || metrics[0];

  return (
    <div className="flex flex-col justify-between space-y-4 rounded-3xl border border-[#1a2922] bg-[#111a16] p-5 sm:p-6">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#b5f542]/15 text-[#b5f542]">
            <BarChart3 className="h-3.5 w-3.5" />
          </div>
          <h3 className="text-sm font-semibold text-white">Live timeframe signals</h3>
        </div>
        <span className="text-[9px] text-[#7f9389]">5 indicator checks · not a probability</span>
      </div>

      {metrics.length === 0 ? (
        <p className="py-8 text-center text-xs text-[#7f9389]">Waiting for live market indicators.</p>
      ) : (
        <>
          <div className="space-y-3">
            {metrics.map((metric) => {
              const isSelected = selectedTf === metric.tf;
              const color =
                metric.bias === 'BULLISH'
                  ? 'from-[#10b981] to-[#b5f542]'
                  : metric.bias === 'BEARISH'
                    ? 'from-[#ff5c5c] to-[#ff8c8c]'
                    : 'from-[#7f9389] to-[#b5f542]';
              return (
                <button
                  type="button"
                  key={metric.tf}
                  onClick={() => setSelectedTf(metric.tf)}
                  className={`w-full rounded-xl p-2 text-left transition-all ${
                    isSelected ? 'border border-[#263d32] bg-[#18261f]' : 'hover:bg-[#16231d]'
                  }`}
                >
                  <div className="mb-1.5 flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-white">{metric.tf}</span>
                      <span className="text-[11px] text-[#7f9389]">{metric.label}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                        metric.bias === 'BULLISH'
                          ? 'bg-[#10b981]/10 text-[#10b981]'
                          : metric.bias === 'BEARISH'
                            ? 'bg-[#ff5c5c]/10 text-[#ff8c8c]'
                            : 'bg-[#b5f542]/10 text-[#b5f542]'
                      }`}>
                        {metric.bias}
                      </span>
                      <span className="font-mono text-xs font-bold text-white">{metric.score}%</span>
                    </div>
                  </div>
                  <div className="h-2.5 w-full overflow-hidden rounded-full border border-[#18261f] bg-[#0c1310]">
                    <div
                      className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-500`}
                      style={{ width: `${metric.score}%` }}
                    />
                  </div>
                </button>
              );
            })}
          </div>

          {activeMetric && (
            <div className="grid grid-cols-3 gap-2 border-t border-[#18261f] pt-3 text-center text-xs">
              <div className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                <span className="block text-[10px] text-[#7f9389]">RSI (14)</span>
                <span className="font-mono font-bold text-white">{activeMetric.rsi.toFixed(2)}</span>
              </div>
              <div className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                <span className="block text-[10px] text-[#7f9389]">EMA ALIGNMENT</span>
                <span className="block truncate text-[10px] font-semibold text-[#b5f542]">{activeMetric.emaStatus}</span>
              </div>
              <div className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                <span className="block text-[10px] text-[#7f9389]">VOLUME RATIO</span>
                <span className="font-mono font-bold text-white">{activeMetric.volumeRatio.toFixed(2)}x</span>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
