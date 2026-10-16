'use client';

import { useState, useMemo } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  ChevronDown, 
  LineChart as LineIcon, 
  CandlestickChart as CandleIcon,
  Columns
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
  currentCapital = 10000.00,
  initialCapital = 10000.00,
  currentBtcPrice = 0,
  marketCandles = [],
  equityHistory
}: BalanceChartCardProps) {
  const [displayMode, setDisplayMode] = useState<'curve' | 'candles' | 'dual'>('curve');
  const [timeframe, setTimeframe] = useState('6 Month');
  const [showTfDropdown, setShowTfDropdown] = useState(false);
  const [hoveredPoint, setHoveredPoint] = useState<EquityPoint | null>(null);
  const candles = marketCandles;

  const returnPct = (((currentCapital - initialCapital) / initialCapital) * 100).toFixed(2);
  const isPositive = currentCapital >= initialCapital;

  // Actual trade equity history points:
  // If not passed from parent, use standard progression starting at $10,000 up to currentCapital
  const points: EquityPoint[] = useMemo(() => {
    if (equityHistory && equityHistory.length > 0) {
      return equityHistory;
    }
    return [
      { label: 'Starting balance', equity: initialCapital, time: '' },
      { label: 'Current equity', equity: currentCapital, time: 'Now' },
    ];
  }, [equityHistory, currentCapital]);

  const broadWidth = 760;
  const broadHeight = 260;

  // Render SVG Candlesticks
  const renderCandlestickView = (customWidth = broadWidth, customHeight = broadHeight) => {
    if (candles.length === 0) return null;
    const minP = Math.min(...candles.map(c => c.low)) - 40;
    const maxP = Math.max(...candles.map(c => c.high)) + 40;
    const range = maxP - minP || 1;
    const cWidth = customWidth / candles.length;

    const getY = (val: number) => customHeight - ((val - minP) / range) * (customHeight - 24) - 12;

    return (
      <svg className="w-full h-full" viewBox={`0 0 ${customWidth} ${customHeight}`} preserveAspectRatio="none">
        {candles.map((c, i) => {
          const isGreen = c.close >= c.open;
          const xCenter = i * cWidth + cWidth / 2;
          const yOpen = getY(c.open);
          const yClose = getY(c.close);
          const yHigh = getY(c.high);
          const yLow = getY(c.low);
          const bodyY = Math.min(yOpen, yClose);
          const bodyH = Math.max(Math.abs(yClose - yOpen), 2.5);
          const bWidth = Math.max(cWidth - 2.5, 2);

          return (
            <g key={i}>
              <line x1={xCenter} y1={yHigh} x2={xCenter} y2={yLow} stroke={isGreen ? '#10b981' : '#ff5c5c'} strokeWidth="1" />
              <rect x={xCenter - bWidth / 2} y={bodyY} width={bWidth} height={bodyH} rx="1" fill={isGreen ? '#10b981' : '#ff5c5c'} />
            </g>
          );
        })}
      </svg>
    );
  };

  // Render 100% Dynamically Calibrated Capital Growth Spline Curve
  const renderSplineCurveView = (customWidth = broadWidth, customHeight = broadHeight) => {
    if (points.length === 0) return null;

    // Calculate real dynamic min and max
    const equities = points.map(p => p.equity);
    const rawMin = Math.min(...equities, initialCapital);
    const rawMax = Math.max(...equities, initialCapital);
    const margin = Math.max((rawMax - rawMin) * 0.25, 100);
    const minVal = rawMin - margin;
    const maxVal = rawMax + margin;
    const valRange = maxVal - minVal || 1;

    // Map each real trade to canvas coordinates
    const coords = points.map((p, i) => {
      const x = points.length === 1
        ? customWidth / 2
        : (i / (points.length - 1)) * (customWidth - 60) + 30;
      const y = customHeight - ((p.equity - minVal) / valRange) * (customHeight - 50) - 25;
      return { x, y, point: p };
    });

    // Build smooth SVG path string from coordinates
    let pathD = `M ${coords[0].x},${coords[0].y}`;
    for (let i = 0; i < coords.length - 1; i++) {
      const p0 = coords[i];
      const p1 = coords[i + 1];
      const midX = (p0.x + p1.x) / 2;
      pathD += ` C ${midX},${p0.y} ${midX},${p1.y} ${p1.x},${p1.y}`;
    }

    const areaD = `${pathD} L ${coords[coords.length - 1].x},${customHeight - 15} L ${coords[0].x},${customHeight - 15} Z`;
    const lastCoord = coords[coords.length - 1];

    return (
      <div className="relative w-full h-full">
        {/* Dynamic Glow backdrop positioned on latest trade point */}
        <div 
          className="absolute rounded-full pointer-events-none opacity-40 blur-3xl transition-all duration-700"
          style={{
            left: `${lastCoord.x - 100}px`,
            top: `${lastCoord.y - 40}px`,
            width: '200px',
            height: '120px',
            background: isPositive 
              ? 'radial-gradient(circle, rgba(181, 245, 66, 0.45) 0%, rgba(16, 185, 129, 0.15) 50%, transparent 70%)'
              : 'radial-gradient(circle, rgba(255, 92, 92, 0.45) 0%, transparent 70%)'
          }}
        ></div>

        <svg className="w-full h-full" viewBox={`0 0 ${customWidth} ${customHeight}`} preserveAspectRatio="none">
          <defs>
            <linearGradient id="realCapGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor={isPositive ? "#b5f542" : "#ff5c5c"} stopOpacity="0.38" />
              <stop offset="70%" stopColor="#10b981" stopOpacity="0.06" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Dynamic Grid lines */}
          <line x1="0" y1="35" x2={customWidth} y2="35" stroke="#16231d" strokeDasharray="3 3" />
          <line x1="0" y1="95" x2={customWidth} y2="95" stroke="#16231d" strokeDasharray="3 3" />
          <line x1="0" y1="155" x2={customWidth} y2="155" stroke="#16231d" strokeDasharray="3 3" />
          <line x1="0" y1="215" x2={customWidth} y2="215" stroke="#16231d" strokeDasharray="3 3" />

          {/* Dynamically Calibrated Area Fill */}
          <path d={areaD} fill="url(#realCapGradient)" />

          {/* Dynamically Calibrated Spline Curve */}
          <path
            d={pathD}
            fill="none"
            stroke={isPositive ? "#b5f542" : "#ff5c5c"}
            strokeWidth="3"
            className="transition-all duration-500"
          />

          {/* Historical Trade Milestone Dots */}
          {coords.map((c, idx) => (
            <g 
              key={idx}
              onMouseEnter={() => setHoveredPoint(c.point)}
              onMouseLeave={() => setHoveredPoint(null)}
              className="cursor-pointer group"
            >
              <circle
                cx={c.x}
                cy={c.y}
                r={idx === coords.length - 1 ? 5.5 : 4}
                fill={idx === coords.length - 1 ? "#b5f542" : "#10b981"}
                stroke="#0c1310"
                strokeWidth="2"
                className="group-hover:scale-125 transition-transform"
              />
            </g>
          ))}

          {/* Latest Trade Glowing beacon */}
          <circle cx={lastCoord.x} cy={lastCoord.y} r="9" fill={isPositive ? "#b5f542" : "#ff5c5c"} fillOpacity="0.35" className="animate-ping" />
        </svg>

        {/* Floating Tooltip displaying Live Calibrated Capital */}
        <div 
          className="absolute z-10 transition-all duration-300 pointer-events-none"
          style={{
            left: `${lastCoord.x}px`,
            top: `${Math.max(lastCoord.y - 32, 25)}px`,
            transform: 'translate(-50%, -50%)'
          }}
        >
          <div className="bg-[#18261f]/95 border border-[#263d32] rounded-2xl py-1.5 px-3 flex items-center space-x-2 shadow-2xl backdrop-blur-md">
            <span className={`w-4 h-4 rounded-full flex items-center justify-center ${
              isPositive ? 'bg-[#b5f542]/20 text-[#b5f542]' : 'bg-[#ff5c5c]/20 text-[#ff5c5c]'
            }`}>
              {isPositive ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
            </span>
            <div className="text-left leading-none">
              <span className="text-xs font-bold text-white font-sans">
                ${hoveredPoint ? hoveredPoint.equity.toLocaleString() : currentCapital.toLocaleString()}
              </span>
              <span className="text-[9px] text-[#7f9389] block mt-0.5">
                {hoveredPoint ? hoveredPoint.label : 'Live Calibrated Capital'}
              </span>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="bg-[#111a16] border border-[#1a2922] rounded-3xl p-5 sm:p-6 space-y-4 relative overflow-hidden flex flex-col justify-between w-full h-full">
      
      {/* Top Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="text-xs font-medium text-[#7f9389]">Agent Capital & Growth Tracker (Real-Time Calibrated)</span>
          <div className="flex items-baseline space-x-2.5 mt-1">
            <span className="text-2xl sm:text-3xl font-bold font-sans text-white tracking-tight">
              ${currentCapital.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full flex items-center gap-1 ${
              isPositive 
                ? 'bg-[#b5f542]/10 border border-[#b5f542]/20 text-[#b5f542]' 
                : 'bg-[#ff5c5c]/10 border border-[#ff5c5c]/20 text-[#ff5c5c]'
            }`}>
              {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
              {isPositive ? '+' : ''}{returnPct}%
            </span>
          </div>
        </div>

        {/* Display Mode Switchers (Curve / Candles / Side-by-Side Dual) */}
        <div className="flex items-center space-x-2">
          <div className="flex items-center bg-[#0c1310] p-1 rounded-xl border border-[#1a2922] text-xs">
            <button
              onClick={() => setDisplayMode('curve')}
              className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 font-medium ${
                displayMode === 'curve' ? 'bg-[#18261f] text-[#b5f542] border border-[#24382f]' : 'text-[#7f9389] hover:text-white'
              }`}
              title="Capital Growth Curve"
            >
              <LineIcon className="w-3.5 h-3.5" />
              <span>Capital</span>
            </button>
            <button
              onClick={() => setDisplayMode('candles')}
              className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 font-medium ${
                displayMode === 'candles' ? 'bg-[#18261f] text-[#b5f542] border border-[#24382f]' : 'text-[#7f9389] hover:text-white'
              }`}
              title="Live BTC Candlesticks"
            >
              <CandleIcon className="w-3.5 h-3.5" />
              <span>Candles</span>
            </button>
            <button
              onClick={() => setDisplayMode('dual')}
              className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 font-medium ${
                displayMode === 'dual' ? 'bg-[#18261f] text-[#b5f542] border border-[#24382f]' : 'text-[#7f9389] hover:text-white'
              }`}
              title="Side by Side Dual Screen"
            >
              <Columns className="w-3.5 h-3.5" />
              <span>Dual</span>
            </button>
          </div>

          {/* Timeframe Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowTfDropdown(!showTfDropdown)}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-[#0c1310] border border-[#1a2922] text-xs font-medium text-white"
            >
              <span>{timeframe}</span>
              <ChevronDown className="w-3 h-3 text-[#7f9389]" />
            </button>
            {showTfDropdown && (
              <div className="absolute right-0 top-full mt-1.5 w-24 bg-[#111a16] border border-[#1a2922] rounded-xl shadow-xl z-20 p-1 text-xs">
                {['15m', '1h', '4h', '1D', '6 Month'].map((tf) => (
                  <button
                    key={tf}
                    onClick={() => {
                      setTimeframe(tf);
                      setShowTfDropdown(false);
                    }}
                    className="w-full text-left px-2 py-1 rounded-lg text-[#7f9389] hover:text-white hover:bg-[#18261f]"
                  >
                    {tf}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Expansive Chart Canvas Area */}
      <div className="h-[280px] sm:h-[310px] w-full select-none">
        {displayMode === 'curve' && (
          <div className="h-full w-full">
            {renderSplineCurveView()}
          </div>
        )}

        {displayMode === 'candles' && (
          <div className="h-full w-full bg-[#0c1310] rounded-2xl border border-[#18261f] p-3.5 flex flex-col justify-between">
            <div className="flex justify-between text-xs text-[#7f9389]">
              <span>BTC/USDT Live Candlesticks</span>
              <span className="text-[#10b981] font-bold">
                {currentBtcPrice > 0 ? `$${currentBtcPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}` : 'Market data unavailable'}
              </span>
            </div>
            <div className="h-[230px] w-full">
              {renderCandlestickView()}
            </div>
          </div>
        )}

        {displayMode === 'dual' && (
          <div className="grid grid-cols-2 gap-4 h-full w-full">
            <div className="bg-[#0c1310] rounded-2xl border border-[#18261f] p-3 flex flex-col justify-between">
              <span className="text-[11px] text-[#7f9389]">Calibrated Capital Trajectory</span>
              <div className="h-[220px] w-full">
                {renderSplineCurveView(360, 220)}
              </div>
            </div>
            <div className="bg-[#0c1310] rounded-2xl border border-[#18261f] p-3 flex flex-col justify-between">
              <span className="text-[11px] text-[#7f9389]">Live Candlestick Bar Graph</span>
              <div className="h-[220px] w-full">
                {renderCandlestickView(360, 220)}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Axis Footer displaying Real Trade Calibration Points */}
      <div className="flex justify-between text-[11px] font-sans text-[#7f9389] pt-1 border-t border-[#18261f]/50">
        <span>Base: ${initialCapital.toLocaleString()}</span>
        <span>Points: {points.length} trade milestones</span>
        <span className="text-[#b5f542] font-semibold">Calibrated From Real PnL</span>
      </div>

    </div>
  );
}
