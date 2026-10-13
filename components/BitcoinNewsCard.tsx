'use client';

import { useState } from 'react';
import { Newspaper, TrendingUp, TrendingDown, ExternalLink, Zap, ShieldCheck } from 'lucide-react';

interface NewsItem {
  id: string;
  title: string;
  source: string;
  time: string;
  sentiment: 'bullish' | 'neutral' | 'bearish';
  impact: 'High' | 'Medium' | 'Low';
  score: string;
}

export function BitcoinNewsCard() {
  const [filter, setFilter] = useState<'all' | 'bullish' | 'impact'>('all');

  const newsItems: NewsItem[] = [
    {
      id: 'news-1',
      title: 'Bitcoin institutional ETF net inflows cross $420M in single session',
      source: 'Bloomberg Crypto',
      time: '12m ago',
      sentiment: 'bullish',
      impact: 'High',
      score: '+88%'
    },
    {
      id: 'news-2',
      title: 'Global BTC mining hashrate hits new all-time high with network difficulty +3.2%',
      source: 'On-Chain Metrics',
      time: '34m ago',
      sentiment: 'bullish',
      impact: 'Medium',
      score: '+74%'
    },
    {
      id: 'news-3',
      title: 'Federal Reserve liquidity index stabilizes near quarterly median',
      source: 'Macro Ledger',
      time: '1h ago',
      sentiment: 'neutral',
      impact: 'High',
      score: '0%'
    },
    {
      id: 'news-4',
      title: 'Exchange Bitcoin reserves decline to multi-year low of 2.14M coins',
      source: 'Glassnode Feed',
      time: '2h ago',
      sentiment: 'bullish',
      impact: 'High',
      score: '+92%'
    }
  ];

  const filteredNews = newsItems.filter(item => {
    if (filter === 'bullish') return item.sentiment === 'bullish';
    if (filter === 'impact') return item.impact === 'High';
    return true;
  });

  return (
    <div className="bg-[#111a16] border border-[#1a2922] rounded-3xl p-5 sm:p-6 space-y-4 flex flex-col justify-between">
      
      {/* Header */}
      <div className="flex items-center justify-between pb-1">
        <div className="flex items-center space-x-2">
          <div className="w-6 h-6 rounded-lg bg-[#b5f542]/15 flex items-center justify-center text-[#b5f542]">
            <Newspaper className="w-3.5 h-3.5" />
          </div>
          <h3 className="text-sm font-semibold text-white">
            Bitcoin News & Sentiment
          </h3>
        </div>

        {/* Filter pills */}
        <div className="flex items-center space-x-1 text-[10px]">
          <button
            onClick={() => setFilter('all')}
            className={`px-2 py-0.5 rounded-md transition-colors ${
              filter === 'all' ? 'bg-[#18261f] text-white font-medium' : 'text-[#7f9389] hover:text-white'
            }`}
          >
            All
          </button>
          <button
            onClick={() => setFilter('bullish')}
            className={`px-2 py-0.5 rounded-md transition-colors ${
              filter === 'bullish' ? 'bg-[#18261f] text-[#b5f542] font-medium' : 'text-[#7f9389] hover:text-white'
            }`}
          >
            Bullish
          </button>
        </div>
      </div>

      {/* News Items List */}
      <div className="space-y-2.5">
        {filteredNews.map((item) => (
          <div 
            key={item.id}
            className="p-2.5 rounded-2xl bg-[#0c1310] border border-[#18261f] hover:border-[#24382f] transition-all group"
          >
            <div className="flex items-start justify-between gap-2">
              <h4 className="text-xs font-medium text-white group-hover:text-[#b5f542] transition-colors leading-snug">
                {item.title}
              </h4>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${
                item.sentiment === 'bullish'
                  ? 'bg-[#10b981]/15 text-[#10b981] border border-[#10b981]/30'
                  : 'bg-[#7f9389]/15 text-[#7f9389] border border-[#7f9389]/30'
              }`}>
                {item.score}
              </span>
            </div>

            <div className="flex items-center justify-between mt-2 text-[10px] text-[#7f9389]">
              <div className="flex items-center space-x-2">
                <span>{item.source}</span>
                <span>•</span>
                <span>{item.time}</span>
              </div>
              <span className="text-[#b5f542] bg-[#b5f542]/10 px-1.5 py-0.5 rounded text-[9px] font-semibold">
                Impact: {item.impact}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Sentiment Ticker Bar */}
      <div className="pt-2 border-t border-[#18261f] flex items-center justify-between text-[11px]">
        <span className="text-[#7f9389]">Aggregated BTC Sentiment:</span>
        <span className="text-[#b5f542] font-bold flex items-center gap-1">
          <TrendingUp className="w-3.5 h-3.5" /> 84% Bullish Bias
        </span>
      </div>

    </div>
  );
}
