'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Bot,
  CheckCircle2,
  Cpu,
  Lock,
  Send,
  ShieldCheck,
  Zap,
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
    leverage: number;
    hash: string;
  };
}

interface LedgerEvent {
  sequence: number;
  event_id: string;
  timestamp_utc: string;
  event_type: string;
  trade_id: string | null;
  payload: Record<string, string | number | null>;
  record_hash: string;
}

interface AgentChatCardProps {
  onAccountChanged?: () => void;
  currentCapital?: number;
}

export function AgentChatCard({
  onAccountChanged,
  currentCapital = 10000,
}: AgentChatCardProps) {
  const [activeTab, setActiveTab] = useState<'chat' | 'ledger'>('chat');
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [ledgerRecords, setLedgerRecords] = useState<LedgerEvent[]>([]);
  const [ledgerValid, setLedgerValid] = useState<boolean | null>(null);
  const [ledgerError, setLedgerError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      sender: 'agent',
      text: 'Mortis paper-trading agent is ready. Live orders are disabled. I analyze BTC using multi-timeframe indicators and deterministic risk controls.',
      time: 'Now',
    },
  ]);

  const loadLedger = useCallback(async () => {
    try {
      const response = await fetch('/api/ledger', { cache: 'no-store' });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Unable to load the audit ledger.');
      }
      setLedgerRecords(result.records || []);
      setLedgerValid(result.valid === true);
      setLedgerError('');
    } catch (error) {
      setLedgerError(error instanceof Error ? error.message : 'Unable to load the audit ledger.');
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (activeTab !== 'ledger') return;
    void loadLedger();
    const interval = setInterval(() => void loadLedger(), 5000);
    return () => clearInterval(interval);
  }, [activeTab, loadLedger]);

  const sendMessage = async (customPrompt?: string) => {
    const textToSend = customPrompt || inputText;
    if (!textToSend.trim()) return;
    setMessages((previous) => [
      ...previous,
      {
        id: `user-${Date.now()}`,
        sender: 'user',
        text: textToSend,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
    if (!customPrompt) setInputText('');
    setIsTyping(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: textToSend }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Mortis analysis failed.');
      }
      const analysis = result.analysis || {};
      const plan = analysis.trade_plan || {};
      const isTrade = plan.action && plan.action !== 'no_trade';
      const record = analysis.decision_record || {};
      setMessages((previous) => [
        ...previous,
        {
          id: `agent-${Date.now()}`,
          sender: 'agent',
          text: result.reply || 'Analysis completed.',
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          tradeData: isTrade
            ? {
                action: plan.action.toUpperCase(),
                entry: plan.entry,
                size: plan.size_btc,
                leverage: plan.leverage || 1,
                hash: record.decision_hash || '',
              }
            : undefined,
        },
      ]);
      if (isTrade) {
        onAccountChanged?.();
        void loadLedger();
      }
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          id: `error-${Date.now()}`,
          sender: 'agent',
          text: error instanceof Error ? error.message : 'Mortis analysis failed.',
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <section className="flex min-h-[620px] flex-col justify-between space-y-5 rounded-3xl border border-[#1a2922] bg-[#111a16] p-6 sm:p-8">
      <div className="flex items-center justify-between border-b border-[#18261f] pb-2">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#b5f542]/15 text-[#b5f542]">
            <Cpu className="h-3.5 w-3.5" />
          </div>
          <h3 className="text-lg font-semibold text-white">Mortis paper agent</h3>
        </div>
        <div className="flex items-center rounded-xl border border-[#1a2922] bg-[#0c1310] p-1 text-[10px]">
          <button
            onClick={() => setActiveTab('chat')}
            className={`rounded-lg px-2.5 py-1 font-bold ${
              activeTab === 'chat' ? 'bg-[#b5f542] text-black' : 'text-[#7f9389] hover:text-white'
            }`}
          >
            Analysis
          </button>
          <button
            onClick={() => setActiveTab('ledger')}
            className={`rounded-lg px-2.5 py-1 font-bold ${
              activeTab === 'ledger' ? 'bg-[#b5f542] text-black' : 'text-[#7f9389] hover:text-white'
            }`}
          >
            Audit ledger
          </button>
        </div>
      </div>

      {activeTab === 'chat' ? (
        <div className="flex flex-1 flex-col justify-between space-y-4">
          <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs">
            <button
              onClick={() => void sendMessage('Analyze BTC market confluence and evaluate a paper trade.')}
              className="flex shrink-0 items-center gap-2 rounded-lg border border-[#1a2922] bg-[#0c1310] px-3 py-2 text-white transition-colors hover:border-[#b5f542]"
            >
              <Zap className="h-3.5 w-3.5 text-[#b5f542]" />
              Analyze BTC
            </button>
            <span             className="shrink-0 rounded-lg border border-[#1a2922] bg-[#0c1310] px-3 py-2 text-[#7f9389]">
              Balance ${currentCapital.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </span>
          </div>

          <div className="h-[420px] space-y-3 overflow-y-auto pr-2 text-sm lg:h-[480px]">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex flex-col ${message.sender === 'user' ? 'items-end' : 'items-start'}`}
              >
                <div
                  className={`max-w-[90%] rounded-2xl p-2.5 leading-relaxed ${
                    message.sender === 'user'
                      ? 'rounded-tr-sm border border-[#263d32] bg-[#18261f] text-white'
                      : 'rounded-tl-sm border border-[#18261f] bg-[#0c1310] text-[#7f9389]'
                  }`}
                >
                  <span className="whitespace-pre-wrap text-sm">{message.text}</span>
                  {message.tradeData && (
                    <div className="mt-2 space-y-0.5 border-t border-[#18261f] pt-1.5 font-mono text-[10px]">
                      <div className="font-bold text-[#b5f542]">PAPER POSITION OPENED · {message.tradeData.leverage}x</div>
                      <div className="text-white">
                        {message.tradeData.action} {message.tradeData.size} BTC @ ${message.tradeData.entry.toLocaleString()}
                      </div>
                      {message.tradeData.hash && (
                        <div className="truncate text-[#7f9389]">Decision SHA-256: {message.tradeData.hash}</div>
                      )}
                    </div>
                  )}
                </div>
                <span className="mt-0.5 px-1 text-[9px] text-[#4b5b53]">{message.time}</span>
              </div>
            ))}
            {isTyping && (
              <div className="flex items-center gap-1 text-[10px] text-[#b5f542]">
                <Bot className="h-3 w-3 animate-pulse" />
                Evaluating market data…
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="flex items-center gap-3 pt-1">
            <input
              type="text"
              placeholder="Ask Mortis to analyze BTC…"
              value={inputText}
              onChange={(event) => setInputText(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && void sendMessage()}
              className="flex-1 rounded-xl border border-[#1a2922] bg-[#0c1310] px-4 py-3 text-sm text-white placeholder-[#4b5b53] focus:border-[#b5f542] focus:outline-none"
            />
            <button
              type="button"
              disabled={isTyping}
              onClick={() => void sendMessage()}
              aria-label="Send message"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#b5f542] text-black shadow transition-colors hover:bg-[#c5fb5a] disabled:opacity-50"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : (
        <div className="h-[480px] space-y-3 overflow-y-auto pr-1">
          <div className="flex items-center justify-between border-b border-[#18261f] pb-2 text-[10px] text-[#7f9389]">
            <span className="flex items-center gap-1">
              <Lock className="h-3 w-3" /> LOCAL SHA-256 HASH CHAIN
            </span>
            <span className={ledgerValid ? 'text-[#10b981]' : 'text-[#ff8c8c]'}>
              {ledgerValid === null ? 'CHECKING' : ledgerValid ? 'VERIFIED' : 'INVALID'}
            </span>
          </div>
          {ledgerError && <p role="alert" className="text-xs text-[#ff8c8c]">{ledgerError}</p>}
          {ledgerRecords.length === 0 && !ledgerError && (
            <p className="py-5 text-center text-xs text-[#7f9389]">No transaction events have been recorded.</p>
          )}
          {ledgerRecords.map((event) => {
            const payload = event.payload;
            const side = typeof payload.side === 'string' ? payload.side.toUpperCase() : '';
            const pnl = typeof payload.pnl_usd === 'number' ? payload.pnl_usd : null;
            return (
              <div
                key={event.event_id}
                className="rounded-xl border border-[#18261f] bg-[#0c1310] p-2.5 font-mono text-[10px]"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-white">
                    #{event.sequence} · {event.event_type.replace('_', ' ').toUpperCase()}
                  </span>
                  <span className="flex items-center gap-1 text-[#10b981]">
                    <CheckCircle2 className="h-3 w-3" />
                    {ledgerValid ? 'HASH OK' : 'CHECK FAILED'}
                  </span>
                </div>
                <div className="mt-1 text-[#7f9389]">
                  {side && `${side} · `}
                  {typeof payload.leverage === 'number' && `${payload.leverage}x · `}
                  {typeof payload.entry === 'number' && `$${payload.entry.toLocaleString()} · `}
                  {typeof payload.size_btc === 'number' && `${payload.size_btc} BTC`}
                  {pnl !== null && (
                    <span className={pnl >= 0 ? 'text-[#10b981]' : 'text-[#ff8c8c]'}>
                      {' '}· net {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-[#4b5b53]">
                  {new Date(event.timestamp_utc).toLocaleString()}
                </div>
                <div className="mt-1 truncate text-[#63766b]">SHA-256: {event.record_hash}</div>
              </div>
            );
          })}
          {ledgerRecords.length > 0 && (
            <button
              type="button"
              onClick={() => void loadLedger()}
              className="w-full rounded-lg border border-[#1a2922] py-2 text-[10px] text-[#7f9389] hover:text-white"
            >
              <ShieldCheck className="mr-1 inline h-3 w-3" /> Re-verify ledger
            </button>
          )}
        </div>
      )}
    </section>
  );
}
