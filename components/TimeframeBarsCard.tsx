'use client';

import { useState } from 'react';
import { BarChart3 } from 'lucide-react';

export interface TimeframeIndicators {
  last_close: number;
  rsi14: number;
  ema20: number;
  ema50: number;
  ema200: number;
  volume_ratio: number;
  atr14: number;
  atr_pct: number;
  support_level: number | null;
  resistance_level: number | null;
  trend_flags: {
    price_above_ema50: boolean;
    ema20_above_ema50: boolean;
    ema50_above_ema200: boolean;
  };
  macd: {
    histogram: number;
    histogram_rising: boolean;
  };
}

type Signal = 'BULLISH' | 'MIXED' | 'BEARISH';

interface TimeframeMetric {
  tf: string;
  label: string;
  agreement: number;
  bias: Signal;
  indicators: TimeframeIndicators;
  signals: Array<{ label: string; result: Signal; detail: string }>;
}

interface TimeframeBarsCardProps {
  timeframes?: Record<string, TimeframeIndicators>;
}

const timeframeLabels: Record<string, string> = {
  '15m': 'Entry momentum',
  '1h': 'Market structure',
  '4h': 'Macro trend',
};

const directionColor: Record<Signal, string> = {
  BULLISH: 'text-[#10b981]',
  MIXED: 'text-[#d6bd69]',
  BEARISH: 'text-[#ff8c8c]',
};

function formatSignal(value: Signal) {
  return value === 'MIXED' ? 'MIXED / NEUTRAL' : value;
}

function buildMetric(tf: string, indicators: TimeframeIndicators): TimeframeMetric {
  const trend: Signal = indicators.trend_flags.price_above_ema50
    && indicators.trend_flags.ema20_above_ema50
    && indicators.trend_flags.ema50_above_ema200
    ? 'BULLISH'
    : !indicators.trend_flags.price_above_ema50
      && !indicators.trend_flags.ema20_above_ema50
      && !indicators.trend_flags.ema50_above_ema200
      ? 'BEARISH'
      : 'MIXED';
  const momentum: Signal = indicators.rsi14 >= 55
    && indicators.macd.histogram > 0
    && indicators.macd.histogram_rising
    ? 'BULLISH'
    : indicators.rsi14 <= 45
      && indicators.macd.histogram < 0
      && !indicators.macd.histogram_rising
      ? 'BEARISH'
      : 'MIXED';

  const signals = [
    {
      label: 'EMA trend',
      result: trend,
      detail: `Price ${indicators.trend_flags.price_above_ema50 ? 'above' : 'below'} EMA 50 · EMA 20 ${indicators.trend_flags.ema20_above_ema50 ? 'above' : 'below'} EMA 50 · EMA 50 ${indicators.trend_flags.ema50_above_ema200 ? 'above' : 'below'} EMA 200`,
    },
    {
      label: 'RSI + MACD momentum',
      result: momentum,
      detail: `RSI ${indicators.rsi14.toFixed(1)} · MACD histogram ${indicators.macd.histogram.toFixed(2)} (${indicators.macd.histogram_rising ? 'rising' : 'falling'})`,
    },
  ];
  const bullish = signals.filter((signal) => signal.result === 'BULLISH').length;
  const bearish = signals.filter((signal) => signal.result === 'BEARISH').length;

  return {
    tf,
    label: timeframeLabels[tf],
    agreement: Math.max(bullish, bearish),
    bias: bullish > bearish ? 'BULLISH' : bearish > bullish ? 'BEARISH' : 'MIXED',
    indicators,
    signals,
  };
}

function formatLevel(price: number | null) {
  return price === null
    ? 'Not identified'
    : `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function TimeframeBarsCard({ timeframes = {} }: TimeframeBarsCardProps) {
  const [selectedTf, setSelectedTf] = useState('1h');
  const metrics = ['15m', '1h', '4h'].flatMap((tf) => {
    const indicators = timeframes[tf];
    return indicators ? [buildMetric(tf, indicators)] : [];
  });
  const activeMetric = metrics.find((metric) => metric.tf === selectedTf) || metrics[0];

  return (
    <section className="flex flex-col space-y-4 rounded-3xl border border-[#1a2922] bg-[#111a16] p-5 sm:p-6">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#b5f542]/15 text-[#b5f542]">
            <BarChart3 className="h-3.5 w-3.5" />
          </div>
          <h2 className="text-sm font-semibold text-white">Live timeframe signals</h2>
        </div>
        <span className="max-w-32 text-right text-[9px] leading-relaxed text-[#7f9389]">
          Rule agreement · not win probability
        </span>
      </div>

      {metrics.length === 0 ? (
        <p className="py-8 text-center text-xs text-[#7f9389]">
          Waiting for live market indicators.
        </p>
      ) : (
        <>
          <div className="space-y-2">
            {metrics.map((metric) => (
              <button
                type="button"
                key={metric.tf}
                onClick={() => setSelectedTf(metric.tf)}
                aria-pressed={selectedTf === metric.tf}
                className={`w-full rounded-xl border p-2 text-left ${
                  selectedTf === metric.tf
                    ? 'border-[#263d32] bg-[#18261f]'
                    : 'border-transparent hover:bg-[#16231d]'
                }`}
              >
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span>
                    <span className="font-mono font-bold text-white">{metric.tf}</span>
                    <span className="ml-2 text-[11px] text-[#7f9389]">{metric.label}</span>
                  </span>
                  <span className={`text-[10px] font-bold ${directionColor[metric.bias]}`}>
                    {metric.bias === 'MIXED'
                      ? 'MIXED'
                      : `${metric.bias} · ${metric.agreement}/2`}
                  </span>
                </div>
              </button>
            ))}
          </div>

          {activeMetric && (
            <div className="space-y-3 border-t border-[#18261f] pt-3">
              <div className="space-y-2">
                {activeMetric.signals.map((signal) => (
                  <div key={signal.label} className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                    <div className="flex items-center justify-between gap-2 text-[10px]">
                      <span className="font-semibold text-white">{signal.label}</span>
                      <span className={`font-bold ${directionColor[signal.result]}`}>
                        {formatSignal(signal.result)}
                      </span>
                    </div>
                    <p className="mt-1 text-[10px] leading-relaxed text-[#7f9389]">
                      {signal.detail}
                    </p>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-2 gap-2 text-center text-[10px]">
                <div className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                  <span className="block text-[#7f9389]">VOLUME VS 20-CANDLE AVG</span>
                  <span className="font-mono font-bold text-white">
                    {activeMetric.indicators.volume_ratio.toFixed(2)}x
                  </span>
                </div>
                <div className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                  <span className="block text-[#7f9389]">ATR VOLATILITY</span>
                  <span className="font-mono font-bold text-white">
                    ${activeMetric.indicators.atr14.toLocaleString()} · {(activeMetric.indicators.atr_pct * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                  <span className="block text-[#7f9389]">NEAREST SUPPORT</span>
                  <span className="font-mono font-bold text-white">
                    {formatLevel(activeMetric.indicators.support_level)}
                  </span>
                </div>
                <div className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2">
                  <span className="block text-[#7f9389]">NEAREST RESISTANCE</span>
                  <span className="font-mono font-bold text-white">
                    {formatLevel(activeMetric.indicators.resistance_level)}
                  </span>
                </div>
              </div>

              <p className="text-[10px] leading-relaxed text-[#7f9389]">
                EMA 20/50/200 compare faster and slower price averages; bullish ordering is
                EMA 20 &gt; EMA 50 &gt; EMA 200. These deterministic checks are correlated
                technical signals, not separate AI agents or calibrated odds, and do not
                guarantee a profitable trade.
              </p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
