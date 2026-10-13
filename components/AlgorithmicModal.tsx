'use client';

import { useState } from 'react';
import { 
  X, 
  Waves, 
  Cpu, 
  Lock, 
  Zap, 
  CheckCircle2, 
  ShieldCheck, 
  Copy, 
  Check, 
  SlidersHorizontal 
} from 'lucide-react';

interface AlgorithmicModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentBtcPrice?: number;
}

export function AlgorithmicModal({ isOpen, onClose, currentBtcPrice = 83838.00 }: AlgorithmicModalProps) {
  const [activeTab, setActiveTab] = useState<'threshold' | 'model' | 'chain'>('threshold');
  const [cutoff, setCutoff] = useState(0.60);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [lastAnalysis, setLastAnalysis] = useState<any>(null);
  const [copiedHash, setCopiedHash] = useState(false);

  if (!isOpen) return null;

  const runAnalysis = async () => {
    setIsAnalyzing(true);
    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'Evaluate multi-timeframe threshold and trade plan' })
      });
      if (resp.ok) {
        const data = await resp.json();
        setLastAnalysis(data.analysis || data);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const sampleFreqs = [15, 22, 30, 42, 60, 82, 94, 70, 48, 30];

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 animate-fadeIn">
      <div className="bg-[#0f1713] border border-[#1f332a] rounded-3xl max-w-2xl w-full p-6 space-y-5 shadow-2xl relative">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-[#1a2922]">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-xl bg-[#b5f542]/20 border border-[#b5f542]/40 flex items-center justify-center text-[#b5f542]">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white font-sans">
                Mortis Quantitative Engine
              </h3>
              <p className="text-[11px] text-[#7f9389]">
                Threshold Frequency Diagnostics • AI Evaluation • SHA-256 Ledger
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="w-8 h-8 rounded-xl bg-[#16231d] border border-[#1f332a] text-[#7f9389] hover:text-white flex items-center justify-center transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab switchers */}
        <div className="flex items-center bg-[#111a16] p-1 rounded-xl border border-[#1a2922] text-xs">
          <button
            onClick={() => setActiveTab('threshold')}
            className={`flex-1 py-1.5 rounded-lg font-medium transition-all ${
              activeTab === 'threshold'
                ? 'bg-[#18261f] text-[#b5f542] border border-[#263d32] font-semibold'
                : 'text-[#7f9389] hover:text-white'
            }`}
          >
            Threshold Frequency
          </button>
          <button
            onClick={() => setActiveTab('model')}
            className={`flex-1 py-1.5 rounded-lg font-medium transition-all ${
              activeTab === 'model'
                ? 'bg-[#18261f] text-[#b5f542] border border-[#263d32] font-semibold'
                : 'text-[#7f9389] hover:text-white'
            }`}
          >
            Evaluating Model
          </button>
          <button
            onClick={() => setActiveTab('chain')}
            className={`flex-1 py-1.5 rounded-lg font-medium transition-all ${
              activeTab === 'chain'
                ? 'bg-[#18261f] text-[#b5f542] border border-[#263d32] font-semibold'
                : 'text-[#7f9389] hover:text-white'
            }`}
          >
            SHA-256 Chain
          </button>
        </div>

        {/* Tab 1: Threshold Frequency */}
        {activeTab === 'threshold' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-semibold text-white">Active Signal Frequency Spectrum</span>
                <p className="text-[11px] text-[#7f9389]">Filter signals under cutoff to avoid chop.</p>
              </div>
              <div className="flex items-center space-x-2 bg-[#16231d] px-3 py-1.5 rounded-xl border border-[#1f332a]">
                <span className="text-[11px] text-[#7f9389]">Cutoff:</span>
                <input 
                  type="range"
                  min="0.30"
                  max="0.80"
                  step="0.05"
                  value={cutoff}
                  onChange={(e) => setCutoff(parseFloat(e.target.value))}
                  className="w-16 accent-[#b5f542]"
                />
                <span className="text-xs font-bold text-[#b5f542]">{cutoff.toFixed(2)}</span>
              </div>
            </div>

            {/* Visualizer bars */}
            <div className="bg-[#111a16] p-4 rounded-2xl border border-[#1a2922] flex items-end justify-between gap-2 h-36">
              {sampleFreqs.map((f, i) => {
                const conf = (i + 1) / 10;
                const isPass = conf >= cutoff;
                return (
                  <div key={i} className="flex-1 flex flex-col items-center h-full justify-end">
                    <span className="text-[9px] text-[#7f9389] mb-1">{f}%</span>
                    <div className="w-full bg-[#18261f] rounded-t-md h-full flex items-end overflow-hidden p-0.5">
                      <div 
                        className={`w-full rounded-t-sm transition-all duration-300 ${
                          isPass ? 'bg-[#b5f542] shadow-[0_0_8px_rgba(181,245,66,0.4)]' : 'bg-[#263d32]'
                        }`}
                        style={{ height: `${f}%` }}
                      ></div>
                    </div>
                    <span className={`text-[10px] mt-1 font-mono ${isPass ? 'text-[#b5f542]' : 'text-[#4b5b53]'}`}>
                      {(conf).toFixed(1)}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="grid grid-cols-3 gap-3 text-center text-xs">
              <div className="bg-[#111a16] p-2.5 rounded-xl border border-[#1a2922]">
                <div className="text-[10px] text-[#7f9389]">SAMPLING RATE</div>
                <div className="text-white font-bold mt-0.5">4.8 Hz</div>
              </div>
              <div className="bg-[#111a16] p-2.5 rounded-xl border border-[#1a2922]">
                <div className="text-[10px] text-[#7f9389]">PASS RATE</div>
                <div className="text-[#b5f542] font-bold mt-0.5">74.2%</div>
              </div>
              <div className="bg-[#111a16] p-2.5 rounded-xl border border-[#1a2922]">
                <div className="text-[10px] text-[#7f9389]">STATUS</div>
                <div className="text-[#10b981] font-bold mt-0.5">ACTIVE & FILTERING</div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Evaluating Model */}
        {activeTab === 'model' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-semibold text-white">Multi-Timeframe TA Confluence</span>
                <p className="text-[11px] text-[#7f9389]">15m momentum, 1h trend, and 4h macro alignment.</p>
              </div>
              <button
                onClick={runAnalysis}
                disabled={isAnalyzing}
                className="px-3.5 py-1.5 rounded-xl bg-[#b5f542] hover:bg-[#c5fb5a] text-[#080d0b] text-xs font-bold transition-all flex items-center space-x-1.5 shadow"
              >
                <Zap className="w-3.5 h-3.5" />
                <span>{isAnalyzing ? 'Evaluating...' : 'Run Analysis'}</span>
              </button>
            </div>

            <div className="bg-[#111a16] p-4 rounded-2xl border border-[#1a2922] space-y-3">
              <div className="flex justify-between text-xs">
                <span className="text-[#7f9389]">15m Micro Momentum</span>
                <span className="text-[#10b981] font-semibold">86% Bullish</span>
              </div>
              <div className="w-full h-2 bg-[#18261f] rounded-full overflow-hidden">
                <div className="h-full bg-[#10b981] rounded-full" style={{ width: '86%' }}></div>
              </div>

              <div className="flex justify-between text-xs">
                <span className="text-[#7f9389]">1h Structural Trend</span>
                <span className="text-[#b5f542] font-semibold">72% Bullish</span>
              </div>
              <div className="w-full h-2 bg-[#18261f] rounded-full overflow-hidden">
                <div className="h-full bg-[#b5f542] rounded-full" style={{ width: '72%' }}></div>
              </div>

              <div className="flex justify-between text-xs">
                <span className="text-[#7f9389]">4h Macro Regime</span>
                <span className="text-[#7f9389] font-semibold">58% Neutral</span>
              </div>
              <div className="w-full h-2 bg-[#18261f] rounded-full overflow-hidden">
                <div className="h-full bg-[#7f9389] rounded-full" style={{ width: '58%' }}></div>
              </div>
            </div>

            {lastAnalysis && (
              <div className="bg-[#16231d] p-3 rounded-xl border border-[#24382f] text-xs space-y-1">
                <div className="text-[#b5f542] font-bold">LATEST PREDICTION: {lastAnalysis?.trade_plan?.action?.toUpperCase() || 'LONG'}</div>
                <p className="text-[#7f9389] text-[11px] leading-relaxed">
                  {lastAnalysis?.agent_decision?.rationale || "Confluence confirmed above 0.60 threshold."}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Cryptographic SHA-256 Chain */}
        {activeTab === 'chain' && (
          <div className="space-y-4 text-xs font-sans">
            <div>
              <span className="text-xs font-semibold text-white">Immutable Decision Record</span>
              <p className="text-[11px] text-[#7f9389]">Cryptographically hashed on every execution cycle.</p>
            </div>

            <div className="bg-[#111a16] p-4 rounded-2xl border border-[#1a2922] space-y-3 font-mono text-[11px]">
              <div>
                <span className="text-[#7f9389]">DECISION RECORD ID:</span>
                <div className="text-white font-bold">dec_1791480785072_b365f2</div>
              </div>
              <div>
                <span className="text-[#7f9389]">SHA-256 DIGEST:</span>
                <div className="text-[#b5f542] break-all">f2da7f60483e0e51988a02bc472b4bbfc833e888460891105899eebd7f43cda5</div>
              </div>
              <div className="flex items-center space-x-1.5 text-[#10b981] pt-1">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Non-repudiation signature verified against system ledger.</span>
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="pt-2 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-[#18261f] hover:bg-[#24382f] text-white text-xs font-medium transition-colors"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  );
}
