'use client';

import { useState } from 'react';
import { 
  Search, 
  Bell, 
  Download, 
  ChevronRight, 
  TrendingDown,
  Sparkles
} from 'lucide-react';

interface TopNavbarProps {
  onOpenEngineModal?: () => void;
  fiatBalance?: string;
  tradingBalance?: string;
}

export function TopNavbar({ 
  onOpenEngineModal,
  tradingBalance = "$2,999.95"
}: TopNavbarProps) {
  const [activeTab, setActiveTab] = useState<'market' | 'trades'>('market');

  return (
    <header className="w-full bg-[#0c1310] border-b border-[#18261f] px-4 sm:px-6 py-3">
      <div className="max-w-[1720px] mx-auto flex flex-wrap items-center justify-between gap-4">
        
        {/* Left: Brand Logo & Mode Tabs */}
        <div className="flex items-center space-x-6">
          {/* Logo */}
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#b5f542] flex items-center justify-center text-black shadow-[0_0_12px_rgba(181,245,66,0.3)]">
              <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
              </svg>
            </div>
            <span className="text-lg font-bold text-white tracking-wide font-sans">
              MORTIS
            </span>
          </div>

          {/* Mode Switch Pills */}
          <div className="flex items-center bg-[#111a16] p-1 rounded-xl border border-[#1a2922]">
            <button
              onClick={() => setActiveTab('market')}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'market'
                  ? 'bg-[#18261f] text-white border border-[#24382f] shadow-sm'
                  : 'text-[#7f9389] hover:text-white'
              }`}
            >
              Market
            </button>
            <button
              onClick={() => setActiveTab('trades')}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'trades'
                  ? 'bg-[#18261f] text-white border border-[#24382f] shadow-sm'
                  : 'text-[#7f9389] hover:text-white'
              }`}
            >
              Trades
            </button>
          </div>
        </div>

        {/* Center: Stat Badges */}
        <div className="hidden lg:flex items-center space-x-4">
          {/* Stat: Trading */}
          <div className="bg-[#111a16] py-1.5 px-3 rounded-2xl border border-[#1a2922] flex items-center space-x-2.5">
            <span className="text-[11px] text-[#7f9389]">Trading</span>
            <span className="text-xs font-semibold text-white">{tradingBalance}</span>
            <span className="text-[10px] font-bold text-[#ff5c5c] bg-[#ff5c5c]/10 border border-[#ff5c5c]/20 px-1.5 py-0.5 rounded-md flex items-center gap-0.5">
              <TrendingDown className="w-2.5 h-2.5" /> 5%
            </span>
          </div>

          {/* Next circle arrow */}
          <button className="w-7 h-7 rounded-full bg-[#111a16] border border-[#1a2922] flex items-center justify-center text-[#7f9389] hover:text-white hover:border-[#24382f] transition-colors">
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Right: Search, Notifications & Deposit Action */}
        <div className="flex items-center space-x-3">
          {/* Engine / Modal trigger */}
          {onOpenEngineModal && (
            <button
              onClick={onOpenEngineModal}
              title="View Algorithm Mechanics & Verification"
              className="hidden sm:flex items-center space-x-1.5 px-3 py-2 rounded-xl bg-[#111a16] hover:bg-[#16231d] border border-[#1a2922] text-[#b5f542] text-xs font-medium transition-all"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Algorithmic Core</span>
            </button>
          )}

          {/* Search Button */}
          <button className="w-9 h-9 rounded-xl bg-[#111a16] border border-[#1a2922] flex items-center justify-center text-[#7f9389] hover:text-white hover:border-[#24382f] transition-colors">
            <Search className="w-4 h-4" />
          </button>

          {/* Notification Bell */}
          <button className="w-9 h-9 rounded-xl bg-[#111a16] border border-[#1a2922] flex items-center justify-center text-[#7f9389] hover:text-white hover:border-[#24382f] transition-colors relative">
            <Bell className="w-4 h-4" />
            <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-[#b5f542] shadow-[0_0_6px_#b5f542]"></span>
          </button>

          {/* Deposit Action Button */}
          <button className="px-4 py-2 rounded-xl bg-[#b5f542] hover:bg-[#c5fb5a] text-[#080d0b] text-xs font-bold transition-all shadow-[0_0_15px_rgba(181,245,66,0.3)] flex items-center space-x-1.5">
            <span>Deposit</span>
            <Download className="w-3.5 h-3.5" />
          </button>
        </div>

      </div>
    </header>
  );
}
