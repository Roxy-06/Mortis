'use client';

import { useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  CandlestickChart as CandleIcon,
  Columns,
  LineChart as LineIcon,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

export interface EquityPoint {
  label: string;
  equity: number;
  time?: string;
}

export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface BalanceChartCardProps {
  currentCapital?: number;
  initialCapital?: number;
  currentBtcPrice?: number;
  marketCandles?: CandleData[];
  equityHistory?: EquityPoint[];
}

export function BalanceChartCard({
  currentCapital = 10000,
  initialCapital = 10000,
  currentBtcPrice = 0,
  marketCandles = [],
  equityHistory,
}: BalanceChartCardProps) {
  const [displayMode, setDisplayMode] = useState<'curve' | 'candles' | 'dual'>('curve');
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const chartScrollRef = useRef<HTMLDivElement>(null);
  const returnPct = initialCapital > 0
    ? (((currentCapital - initialCapital) / initialCapital) * 100).toFixed(2)
    : '0.00';
  const isPositive = currentCapital >= initialCapital;
  const points = useMemo<EquityPoint[]>(() => (
    equityHistory?.length
      ? equityHistory
      : [
          { label: 'Starting balance', equity: initialCapital, time: '' },
          { label: 'Current equity', equity: currentCapital, time: 'Now' },
        ]
  ), [equityHistory, initialCapital, currentCapital]);

  const chartWidth = Math.max(760, (points.length - 1) * 48 + 60);
  const chartHeight = 260;

  const renderCandlesticks = (width = 760, height = chartHeight) => {
    if (marketCandles.length === 0) {
      return <p className="py-16 text-center text-xs text-[#7f9389]">Market candles unavailable.</p>;
    }

    const minPrice = Math.min(...marketCandles.map((candle) => candle.low)) - 40;
    const maxPrice = Math.max(...marketCandles.map((candle) => candle.high)) + 40;
    const priceRange = maxPrice - minPrice || 1;
    const candleWidth = width / marketCandles.length;
    const getY = (price: number) => height - ((price - minPrice) / priceRange) * (height - 24) - 12;

    return (
      <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {marketCandles.map((candle, index) => {
          const isGreen = candle.close >= candle.open;
          const x = index * candleWidth + candleWidth / 2;
          const yOpen = getY(candle.open);
          const yClose = getY(candle.close);
          const color = isGreen ? '#10b981' : '#ff5c5c';
          return (
            <g key={candle.time}>
              <line x1={x} y1={getY(candle.high)} x2={x} y2={getY(candle.low)} stroke={color} />
              <rect
                x={x - Math.max(candleWidth - 2.5, 2) / 2}
                y={Math.min(yOpen, yClose)}
                width={Math.max(candleWidth - 2.5, 2)}
                height={Math.max(Math.abs(yClose - yOpen), 2.5)}
                rx="1"
                fill={color}
              />
            </g>
          );
        })}
      </svg>
    );
  };

  const renderEquityCurve = (width = chartWidth, height = chartHeight) => {
    if (points.length === 0) return null;
    const values = points.map((point) => point.equity);
    const rawMin = Math.min(...values, initialCapital);
    const rawMax = Math.max(...values, initialCapital);
    const margin = Math.max((rawMax - rawMin) * 0.25, 100);
    const minValue = rawMin - margin;
    const valueRange = rawMax + margin - minValue || 1;
    const coords = points.map((point, index) => ({
      x: points.length === 1 ? width / 2 : (index / (points.length - 1)) * (width - 60) + 30,
      y: height - ((point.equity - minValue) / valueRange) * (height - 50) - 25,
      point,
    }));
    let path = `M ${coords[0].x},${coords[0].y}`;
    for (let index = 0; index < coords.length - 1; index++) {
      const current = coords[index];
      const next = coords[index + 1];
      const middleX = (current.x + next.x) / 2;
      path += ` C ${middleX},${current.y} ${middleX},${next.y} ${next.x},${next.y}`;
    }
    const area = `${path} L ${coords[coords.length - 1].x},${height - 15} L ${coords[0].x},${height - 15} Z`;
    const activeIndex = Math.min(hoveredIndex ?? selectedIndex ?? coords.length - 1, coords.length - 1);
    const activePoint = coords[activeIndex].point;
    const lastCoord = coords[coords.length - 1];
    const curveColor = isPositive ? '#b5f542' : '#ff5c5c';

    return (
      <div className="flex h-full flex-col">
        <svg
          className="min-h-0 flex-1"
          width={width}
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Simulated account equity by trade, oldest to newest"
        >
          <defs>
            <linearGradient id="equityFill" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor={curveColor} stopOpacity="0.3" />
              <stop offset="72%" stopColor={curveColor} stopOpacity="0.06" />
              <stop offset="100%" stopColor={curveColor} stopOpacity="0" />
            </linearGradient>
            <radialGradient id="equityEndGlow">
              <stop offset="0%" stopColor={curveColor} stopOpacity="0.3" />
              <stop offset="55%" stopColor={curveColor} stopOpacity="0.12" />
              <stop offset="100%" stopColor={curveColor} stopOpacity="0" />
            </radialGradient>
            <filter id="equityLineGlow" x="-30%" y="-100%" width="160%" height="300%">
              <feGaussianBlur stdDeviation="4" />
            </filter>
          </defs>
          {[35, 95, 155, 215].map((y) => (
            <line key={y} x1="0" y1={y} x2={width} y2={y} stroke="#16231d" strokeDasharray="3 3" />
          ))}
          <ellipse
            cx={lastCoord.x}
            cy={lastCoord.y}
            rx="115"
            ry="72"
            fill="url(#equityEndGlow)"
            pointerEvents="none"
          />
          <path d={area} fill="url(#equityFill)" />
          <path
            d={path}
            fill="none"
            stroke={curveColor}
            strokeWidth="8"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity="0.45"
            filter="url(#equityLineGlow)"
          />
          <path
            d={path}
            fill="none"
            stroke={curveColor}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {coords.map((coord, index) => (
            <g
              key={`${coord.point.label}-${index}`}
              role="button"
              tabIndex={0}
              aria-label={`${coord.point.label}: $${coord.point.equity.toFixed(2)}${coord.point.time ? ` at ${coord.point.time} UTC` : ''}`}
              onMouseEnter={() => setHoveredIndex(index)}
              onMouseLeave={() => setHoveredIndex(null)}
              onFocus={() => setHoveredIndex(index)}
              onBlur={() => setHoveredIndex(null)}
              onClick={() => setSelectedIndex((previous) => previous === index ? null : index)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelectedIndex((previous) => previous === index ? null : index);
                }
              }}
              className="cursor-pointer"
            >
              <circle cx={coord.x} cy={coord.y} r="12" fill="transparent" />
              <circle
                cx={coord.x}
                cy={coord.y}
                r={index === activeIndex ? 5 : 3.5}
                fill={curveColor}
                stroke={index === activeIndex ? '#ffffff' : '#0c1310'}
                strokeWidth="1.5"
              />
            </g>
          ))}
          <circle
            cx={lastCoord.x}
            cy={lastCoord.y}
            r="15"
            fill="none"
            stroke={curveColor}
            strokeWidth="1"
            opacity="0.35"
            pointerEvents="none"
          />
        </svg>
        <div className="flex items-center justify-between gap-3 border-t border-[#18261f] px-2 py-2 text-[10px]">
          <span className="truncate text-[#7f9389]">
            {activePoint.label}{activePoint.time ? ` · ${activePoint.time} UTC` : ''}
          </span>
          <span className="shrink-0 font-mono font-semibold text-white">
            ${activePoint.equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
      </div>
    );
  };

  const modeButton = (
    mode: 'curve' | 'candles' | 'dual',
    label: string,
    Icon: typeof LineIcon,
  ) => (
    <button
      key={mode}
      type="button"
      onClick={() => setDisplayMode(mode)}
      aria-pressed={displayMode === mode}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ${
        displayMode === mode
          ? 'border border-[#24382f] bg-[#18261f] text-[#b5f542]'
          : 'text-[#7f9389] hover:text-white'
      }`}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );

  return (
    <section className="flex h-full w-full flex-col justify-between space-y-4 overflow-hidden rounded-3xl border border-[#1a2922] bg-[#111a16] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="text-xs font-medium text-[#7f9389]">Simulated account equity · trade-by-trade</span>
          <div className="mt-1 flex items-baseline gap-2.5">
            <span className="font-sans text-2xl font-bold tracking-tight text-white sm:text-3xl">
              ${currentCapital.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <span className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${
              isPositive
                ? 'border-[#b5f542]/20 bg-[#b5f542]/10 text-[#b5f542]'
                : 'border-[#ff5c5c]/20 bg-[#ff5c5c]/10 text-[#ff5c5c]'
            }`}>
              {isPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {isPositive ? '+' : ''}{returnPct}%
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center rounded-xl border border-[#1a2922] bg-[#0c1310] p-1">
            {modeButton('curve', 'Capital', LineIcon)}
            {modeButton('candles', 'Candles', CandleIcon)}
            {modeButton('dual', 'Dual', Columns)}
          </div>
          {displayMode === 'curve' && points.length > 16 && (
            <button
              type="button"
              onClick={() => {
                chartScrollRef.current?.scrollTo({ left: chartScrollRef.current.scrollWidth, behavior: 'auto' });
                setSelectedIndex(null);
              }}
              className="inline-flex items-center gap-1 rounded-xl border border-[#1a2922] bg-[#0c1310] px-3 py-2 text-[10px] font-medium text-[#cbd5cf] hover:text-white"
            >
              Latest <ArrowRight className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      <div className="h-[280px] w-full select-none sm:h-[310px]">
        {displayMode === 'curve' && (
          <div
            ref={chartScrollRef}
            className="h-full w-full overflow-x-auto overflow-y-hidden rounded-2xl border border-[#18261f] bg-[#0c1310]"
            role="region"
            aria-label="Scrollable account equity history"
            tabIndex={0}
          >
            <div className="h-full" style={{ width: `${chartWidth}px` }}>
              {renderEquityCurve()}
            </div>
          </div>
        )}

        {displayMode === 'candles' && (
          <div className="flex h-full w-full flex-col justify-between rounded-2xl border border-[#18261f] bg-[#0c1310] p-3.5">
            <div className="flex justify-between text-xs text-[#7f9389]">
              <span>BTC/USDT · recent 15-minute candles</span>
              <span className="font-bold text-[#10b981]">
                {currentBtcPrice > 0
                  ? `$${currentBtcPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                  : 'Market data unavailable'}
              </span>
            </div>
            <div className="h-[230px] w-full">{renderCandlesticks()}</div>
          </div>
        )}

        {displayMode === 'dual' && (
          <div className="grid h-full w-full grid-cols-2 gap-4">
            <div className="flex flex-col justify-between rounded-2xl border border-[#18261f] bg-[#0c1310] p-3">
              <span className="text-[11px] text-[#7f9389]">Historical simulated equity</span>
              <div className="h-[220px] w-full overflow-x-auto">{renderEquityCurve()}</div>
            </div>
            <div className="flex flex-col justify-between rounded-2xl border border-[#18261f] bg-[#0c1310] p-3">
              <span className="text-[11px] text-[#7f9389]">Recent BTC/USDT candles</span>
              <div className="h-[220px] w-full">{renderCandlesticks(360, 220)}</div>
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-between border-t border-[#18261f]/50 pt-1 font-sans text-[11px] text-[#7f9389]">
        <span>Start: ${initialCapital.toLocaleString()}</span>
        <span>{points.length} equity points</span>
        <span className="font-semibold text-[#b5f542]">Oldest to newest · paper only</span>
      </div>
    </section>
  );
}
