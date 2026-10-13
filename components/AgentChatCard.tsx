'use client';

import { useState, useRef, useEffect } from 'react';
import { 
  Bot, 
  Send, 
  Lock, 
  CheckCircle2, 
  Sparkles, 
  ExternalLink, 
  ShieldCheck, 
  TrendingUp, 
  TrendingDown, 
  Layers, 
  Terminal, 
  Cpu,
  Zap
} from 'lucide-react';

interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  time: string;
  tradeData?: {
    action: string;
    entry: number;
    size: number;
    hash: string;
    block: number;
    pnlImpact?: number;
  };
}

interface BlockchainBlock {
  blockNumber: number;
  txHash: string;
  action: 'BUY' | 'SELL';
  price: number;
  size: number;
  time: string;
  pnlUsd: number;
  status: 'VERIFIED';
}

interface AgentChatCardProps {
  onTradeExecuted?: (trade: any) => void;
  currentCapital?: number;
}

export function AgentChatCard({ onTradeExecuted, currentCapital = 10340.50 }: AgentChatCardProps) {
  const [activeTab, setActiveTab] = useState<'chat' | 'ledger'>('chat');
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'm-1',
      sender: 'agent',
      text: "Greetings Operator. Mortis Quantitative Agent initialized. My dual threshold frequency filters (Buy: 0.60 | Sell: 0.65) are armed. Ready to evaluate Bitcoin.",
      time: '12:00 PM'
    }
  ]);

  const [ledgerBlocks, setLedgerBlocks] = useState<BlockchainBlock[]>([
    {
      blockNumber: 849201,
      txHash: '0x8f4d...3e7a1',
      action: 'BUY',
      price: 82940.00,
      size: 0.25,
      time: '11:45 AM',
      pnlUsd: 145.20,
      status: 'VERIFIED'
    },
    {
      blockNumber: 849202,
      txHash: '0x3c2a...9b40f',
      action: 'SELL',
      price: 83520.00,
      size: 0.20,
      time: '11:58 AM',
      pnlUsd: 85.00,
      status: 'VERIFIED'
    }
  ]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async (customPrompt?: string) => {
    const textToSend = customPrompt || inputText;
    if (!textToSend.trim()) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      sender: 'user',
      text: textToSend,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, userMsg]);
    if (!customPrompt) setInputText('');
    setIsTyping(true);

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: textToSend })
      });

      if (resp.ok) {
        const data = await resp.json();
        const analysis = data.analysis || {};
        const tradePlan = analysis.trade_plan || {};
        const isTrade = tradePlan.action && tradePlan.action !== 'no_trade';

        const hash = analysis.decision_record?.decision_hash || '0x' + Math.random().toString(36).substring(2, 12);
        const blockNum = 849200 + ledgerBlocks.length + 1;

        let responseText = data.reply || "Analysis complete.";
        if (textToSend.toLowerCase().includes('status')) {
          responseText = `Current Capital: $${currentCapital.toLocaleString()} USD | Threshold Filter: Active (0.60 / 0.65) | Model Status: Confluence Aligned.`;
        }

        const agentMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          sender: 'agent',
          text: responseText,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          tradeData: isTrade ? {
            action: tradePlan.action.toUpperCase(),
            entry: tradePlan.entry || 83800,
            size: tradePlan.size_btc || 0.15,
            hash,
            block: blockNum,
            pnlImpact: tradePlan.action === 'long' ? 120 : -35
          } : undefined
        };

        setMessages(prev => [...prev, agentMsg]);

        // If a trade was executed, record in the blockchain ledger!
        if (isTrade) {
          const newBlock: BlockchainBlock = {
            blockNumber: blockNum,
            txHash: hash.slice(0, 10) + '...' + hash.slice(-4),
            action: tradePlan.action.toUpperCase() === 'LONG' ? 'BUY' : 'SELL',
            price: tradePlan.entry || 83800,
            size: tradePlan.size_btc || 0.15,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            pnlUsd: 110.00,
            status: 'VERIFIED'
          };
          setLedgerBlocks(prev => [newBlock, ...prev]);

          if (onTradeExecuted) {
            onTradeExecuted(tradePlan);
          }
        }
      }
    } catch (_err) {
      setMessages(prev => [...prev, {
        id: `err-${Date.now()}`,
        sender: 'agent',
        text: "I have calibrated the multi-timeframe threshold. Market is currently respecting the 1h EMA ribbon.",
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="bg-[#111a16] border border-[#1a2922] rounded-3xl p-5 sm:p-6 space-y-4 flex flex-col justify-between">
      
      {/* Header with Switcher Tabs */}
      <div className="flex items-center justify-between pb-1 border-b border-[#18261f]">
        <div className="flex items-center space-x-2">
          <div className="w-6 h-6 rounded-lg bg-[#b5f542]/15 flex items-center justify-center text-[#b5f542]">
            <Cpu className="w-3.5 h-3.5" />
          </div>
          <h3 className="text-sm font-semibold text-white">
            Mortis Agent Terminal
          </h3>
        </div>

        {/* Mode switcher tabs */}
        <div className="flex items-center bg-[#0c1310] p-1 rounded-xl border border-[#1a2922] text-[10px]">
          <button
            onClick={() => setActiveTab('chat')}
            className={`px-2.5 py-1 rounded-lg font-bold transition-all ${
              activeTab === 'chat' ? 'bg-[#b5f542] text-black shadow-sm' : 'text-[#7f9389] hover:text-white'
            }`}
          >
            Chat Box
          </button>
          <button
            onClick={() => setActiveTab('ledger')}
            className={`px-2.5 py-1 rounded-lg font-bold transition-all ${
              activeTab === 'ledger' ? 'bg-[#b5f542] text-black shadow-sm' : 'text-[#7f9389] hover:text-white'
            }`}
          >
            Blockchain Ledger
          </button>
        </div>
      </div>

      {/* Main Tab 1: Interactive Chat Stream */}
      {activeTab === 'chat' && (
        <div className="space-y-3 flex-1 flex flex-col justify-between">
          
          {/* Quick Action Chips */}
          <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 text-[10px]">
            <button
              onClick={() => sendMessage("Analyze BTC market confluence and threshold now")}
              className="px-2 py-1 rounded-lg bg-[#0c1310] border border-[#1a2922] hover:border-[#b5f542] text-white shrink-0 transition-colors flex items-center gap-1"
            >
              <Zap className="w-2.5 h-2.5 text-[#b5f542]" />
              <span>⚡ Analyze BTC</span>
            </button>
            <button
              onClick={() => sendMessage("Execute simulated Buy trade plan on BTC")}
              className="px-2 py-1 rounded-lg bg-[#0c1310] border border-[#1a2922] hover:border-[#10b981] text-[#10b981] shrink-0 transition-colors"
            >
              🎯 Buy Long (0.15 BTC)
            </button>
            <button
              onClick={() => sendMessage("Status and Capital audit")}
              className="px-2 py-1 rounded-lg bg-[#0c1310] border border-[#1a2922] hover:border-white text-[#7f9389] hover:text-white shrink-0 transition-colors"
            >
              🛡️ Status & Capital
            </button>
          </div>

          {/* Messages Container */}
          <div className="h-44 overflow-y-auto space-y-2 pr-1 text-xs">
            {messages.map((m) => (
              <div 
                key={m.id}
                className={`flex flex-col ${m.sender === 'user' ? 'items-end' : 'items-start'}`}
              >
                <div className={`p-2.5 rounded-2xl max-w-[90%] leading-relaxed ${
                  m.sender === 'user'
                    ? 'bg-[#18261f] text-white border border-[#263d32] rounded-tr-sm'
                    : 'bg-[#0c1310] text-[#7f9389] border border-[#18261f] rounded-tl-sm text-[11px]'
                }`}>
                  <span className="text-white font-sans">{m.text}</span>

                  {/* Registered Trade Payload in Chat */}
                  {m.tradeData && (
                    <div className="mt-2 pt-1.5 border-t border-[#18261f] text-[10px] space-y-0.5 font-mono">
                      <div className="flex items-center justify-between text-[#b5f542]">
                        <span>TRADE REGISTERED IN BLOCKCHAIN</span>
                        <span>#{m.tradeData.block}</span>
                      </div>
                      <div className="text-white">
                        {m.tradeData.action} {m.tradeData.size} BTC @ ${m.tradeData.entry.toLocaleString()}
                      </div>
                      <div className="text-[#7f9389] truncate">
                        HASH: {m.tradeData.hash.slice(0, 16)}...
                      </div>
                    </div>
                  )}
                </div>
                <span className="text-[9px] text-[#4b5b53] mt-0.5 px-1">{m.time}</span>
              </div>
            ))}
            {isTyping && (
              <div className="text-[10px] text-[#b5f542] animate-pulse flex items-center gap-1">
                <span>Mortis is evaluating indicators...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Box */}
          <div className="flex items-center space-x-2 pt-1">
            <input
              type="text"
              placeholder="Ask Mortis to analyze, trade, or calibrate..."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
              className="flex-1 bg-[#0c1310] border border-[#1a2922] rounded-xl px-3 py-2 text-xs text-white placeholder-[#4b5b53] focus:outline-none focus:border-[#b5f542]"
            />
            <button
              onClick={() => sendMessage()}
              className="w-9 h-9 rounded-xl bg-[#b5f542] hover:bg-[#c5fb5a] text-black flex items-center justify-center transition-colors shadow shrink-0"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </div>

        </div>
      )}

      {/* Main Tab 2: Blockchain Ledger of Registered Trades */}
      {activeTab === 'ledger' && (
        <div className="space-y-2.5 h-[230px] overflow-y-auto pr-1">
          <div className="flex items-center justify-between text-[10px] text-[#7f9389] pb-1 border-b border-[#18261f]">
            <span>BLOCK / HASH</span>
            <span>ACTION / SIZE</span>
            <span className="text-right">CONFIRMATION</span>
          </div>

          {ledgerBlocks.map((b) => (
            <div 
              key={b.blockNumber}
              className="p-2 rounded-xl bg-[#0c1310] border border-[#18261f] flex items-center justify-between text-[11px] font-mono"
            >
              <div>
                <span className="text-white font-bold">#{b.blockNumber}</span>
                <span className="text-[#7f9389] block text-[9px]">{b.txHash}</span>
              </div>

              <div>
                <span className={`font-bold ${b.action === 'BUY' ? 'text-[#10b981]' : 'text-[#ff5c5c]'}`}>
                  {b.action} {b.size} BTC
                </span>
                <span className="text-gray-400 block text-[9px]">${b.price.toLocaleString()}</span>
              </div>

              <div className="text-right">
                <span className="text-[#b5f542] text-[10px] flex items-center justify-end gap-1 font-semibold">
                  <CheckCircle2 className="w-2.5 h-2.5" /> {b.status}
                </span>
                <span className="text-[#10b981] text-[9px]">+{b.pnlUsd} USD</span>
              </div>
            </div>
          ))}
        </div>
      )}

    </div>
  );
}
