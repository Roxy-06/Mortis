'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { TrendingDown, TrendingUp } from 'lucide-react';
import { TopNavbar } from '../components/TopNavbar';
import { Sidebar } from '../components/Sidebar';
import { BalanceChartCard } from '../components/BalanceChartCard';
import { RiskAnalysisCard } from '../components/RiskAnalysisCard';
import { TimeframeBarsCard } from '../components/TimeframeBarsCard';
import { BitcoinNewsCard } from '../components/BitcoinNewsCard';
import { AgentChatCard } from '../components/AgentChatCard';
import { AlgorithmicModal } from '../components/AlgorithmicModal';
import { ManualTradePanel, type OpenPosition } from '../components/ManualTradePanel';
import type { CandleData } from '../components/BalanceChartCard';
import { type TimeframeIndicators } from '../components/TimeframeBarsCard';

export default function Home() {
  const [activeNav, setActiveNav] = useState('discover');
  const [isEngineModalOpen, setIsEngineModalOpen] = useState(false);
  
  // Real-time Capital & Bitcoin metrics
  const [initialCapital, setInitialCapital] = useState(10000.00);
  const [currentCapital, setCurrentCapital] = useState(10000.00);
  const [availableBalance, setAvailableBalance] = useState(10000.00);
  const [totalTrades, setTotalTrades] = useState(0);
  const [winRate, setWinRate] = useState(0);
  const [maxDrawdownPct, setMaxDrawdownPct] = useState(0);
  const [todayRealizedPnl, setTodayRealizedPnl] = useState(0);
  const [currentBtcPrice, setCurrentBtcPrice] = useState(0);
  const [btcPriceDirection, setBtcPriceDirection] = useState<'up' | 'down' | 'flat'>('flat');
  const previousBtcPrice = useRef(0);
  const [openPosition, setOpenPosition] = useState<OpenPosition | null>(null);
  const [marketCandles, setMarketCandles] = useState<CandleData[]>([]);
  const [timeframes, setTimeframes] = useState<Record<string, TimeframeIndicators>>({});
  const [dashboardError, setDashboardError] = useState('');

  const [equityHistory, setEquityHistory] = useState<Array<{ label: string; equity: number; time: string }>>([
    { label: 'Starting balance', equity: 10000.00, time: '' },
    { label: 'Current equity', equity: 10000.00, time: 'Now' }
  ]);

  const syncAccountData = useCallback(async () => {
    try {
      const resp = await fetch('/api/account', { cache: 'no-store' });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Paper-trading backend is unavailable.');
      }
      setCurrentCapital(data.equity);
      setAvailableBalance(data.available_balance);
      setInitialCapital(data.starting_equity);
      setTotalTrades(data.total_trades);
      setWinRate(data.win_rate);
      setMaxDrawdownPct(data.max_drawdown_pct);
      setTodayRealizedPnl(data.today_realized_pnl_usd);
      setOpenPosition(data.open_position);
      setEquityHistory(data.equity_history);
      setDashboardError('');
    } catch (error) {
      setDashboardError(error instanceof Error ? error.message : 'Account data could not be loaded.');
    }
  }, []);

  const syncMarketData = useCallback(async () => {
    try {
      const resp = await fetch('/api/snapshot', { cache: 'no-store' });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Live Bitcoin market data is unavailable.');
      }
      const previousPrice = previousBtcPrice.current;
      setBtcPriceDirection(
        previousPrice === 0
          ? 'flat'
          : data.price > previousPrice
            ? 'up'
            : data.price < previousPrice
              ? 'down'
              : 'flat',
      );
      previousBtcPrice.current = data.price;
      setCurrentBtcPrice(data.price);
      setMarketCandles(data.candles || []);
      setTimeframes(data.timeframes || {});
    } catch (error) {
      setMarketCandles([]);
      setDashboardError(error instanceof Error ? error.message : 'Market data could not be loaded.');
    }
  }, []);

  useEffect(() => {
    syncAccountData();
    syncMarketData();
    const interval = setInterval(() => {
      syncAccountData();
      syncMarketData();
    }, 4000);
    return () => clearInterval(interval);
  }, [syncAccountData, syncMarketData]);

  const handleResetAccount = async () => {
    try {
      const response = await fetch('/api/account/reset', { method: 'POST' });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Account reset failed.');
      }
      await syncAccountData();
    } catch (error) {
      setDashboardError(error instanceof Error ? error.message : 'Account reset failed.');
    }
  };

  return (
    <div className="min-h-screen bg-[#080d0b] text-white flex flex-col font-sans select-none antialiased">
      
      {/* 1. Top Navbar */}
      <TopNavbar 
        onOpenEngineModal={() => setIsEngineModalOpen(true)}
        tradingBalance={`$${currentCapital.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
      />

      {/* 2. Main Dashboard Layout Area */}
      <main className="flex-1 max-w-[1720px] w-full mx-auto p-4 sm:p-6 lg:p-8">
        
        {/* Outer Dashboard Slate Container Frame */}
        <div className="bg-[#0c1310] border border-[#18261f] rounded-[2rem] p-4 sm:p-6 lg:p-7 shadow-2xl flex flex-col md:flex-row gap-6">
          
          {/* Left Navigation Sidebar */}
          <Sidebar 
            activeView={activeNav}
            onSelectView={setActiveNav}
            onOpenEngineModal={() => setIsEngineModalOpen(true)}
          />

          {/* Right Main Grid Workspace */}
          <div className="flex-1 flex flex-col space-y-6">
            <section className="flex flex-wrap items-center justify-between gap-4 rounded-3xl border border-[#1a2922] bg-[#111a16] px-6 py-5 sm:px-8 sm:py-6">
              <div>
                <p className="text-sm font-medium uppercase tracking-[0.2em] text-[#7f9389]">
                  Bitcoin · BTC/USDT
                </p>
                <p
                  aria-live="polite"
                  className={`mt-2 text-4xl font-bold tracking-tight sm:text-6xl ${
                    btcPriceDirection === 'up'
                      ? 'text-[#10b981]'
                      : btcPriceDirection === 'down'
                        ? 'text-[#ff5c5c]'
                        : 'text-white'
                  }`}
                >
                  {currentBtcPrice > 0
                    ? `$${currentBtcPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    : 'Waiting for live price…'}
                </p>
              </div>
              <div
                className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold ${
                  btcPriceDirection === 'up'
                    ? 'border-[#10b981]/30 bg-[#10b981]/10 text-[#10b981]'
                    : btcPriceDirection === 'down'
                      ? 'border-[#ff5c5c]/30 bg-[#ff5c5c]/10 text-[#ff8c8c]'
                      : 'border-[#263d32] bg-[#0c1310] text-[#7f9389]'
                }`}
              >
                {btcPriceDirection === 'up' ? (
                  <TrendingUp className="h-5 w-5" />
                ) : btcPriceDirection === 'down' ? (
                  <TrendingDown className="h-5 w-5" />
                ) : null}
                {btcPriceDirection === 'up'
                  ? 'Moving up'
                  : btcPriceDirection === 'down'
                    ? 'Moving down'
                    : 'Live market price'}
              </div>
            </section>
            
            {/* Top Row: Balance / Candlestick Chart (Left) + Risk Analysis & Dual Threshold (Right) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
              
              {/* Capital Spline / Candlesticks / Dual View (Expansive 8 cols) */}
              <div className="lg:col-span-8 flex">
                <div className="w-full">
                  <BalanceChartCard 
                    currentCapital={currentCapital}
                    initialCapital={initialCapital}
                    currentBtcPrice={currentBtcPrice}
                    marketCandles={marketCandles}
                    equityHistory={equityHistory}
                  />
                </div>
              </div>

              {/* Agent Risk & Dual Threshold Engine (Compact 4 cols) */}
              <div className="lg:col-span-4 flex">
                <div className="w-full">
                  <RiskAnalysisCard 
                    initialCapital={initialCapital}
                    currentEquity={currentCapital}
                    totalTrades={totalTrades}
                    winRate={winRate}
                    maxDrawdownPct={maxDrawdownPct}
                    todayRealizedPnl={todayRealizedPnl}
                    onResetAccount={handleResetAccount}
                  />
                </div>
              </div>

            </div>

            {dashboardError && (
              <p role="alert" className="rounded-xl border border-[#ff5c5c]/30 bg-[#ff5c5c]/10 px-4 py-3 text-xs text-[#ffaaaa]">
                {dashboardError}
              </p>
            )}

            <ManualTradePanel
              availableBalance={availableBalance}
              currentPrice={currentBtcPrice}
              openPosition={openPosition}
              onAccountChanged={syncAccountData}
            />

            {/* Market context cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              
              {/* 1. Multi-Timeframe Confluence Bar Graphs */}
              <div>
                <TimeframeBarsCard timeframes={timeframes} />
              </div>

              {/* 2. Bitcoin News & Market Sentiment */}
              <div>
                <BitcoinNewsCard />
              </div>

            </div>

            <AgentChatCard
              onAccountChanged={syncAccountData}
              currentCapital={currentCapital}
            />
          </div>

        </div>

      </main>

      {/* Algorithmic Diagnostics & Deep Threshold Modal */}
      <AlgorithmicModal
        isOpen={isEngineModalOpen}
        onClose={() => setIsEngineModalOpen(false)}
        currentBtcPrice={currentBtcPrice}
      />

    </div>
  );
}