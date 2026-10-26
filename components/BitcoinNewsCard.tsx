import { Newspaper } from 'lucide-react';

export function BitcoinNewsCard() {
  return (
    <section className="flex min-h-64 flex-col rounded-3xl border border-[#1a2922] bg-[#111a16] p-5 sm:p-6">
      <div className="flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#b5f542]/15 text-[#b5f542]">
          <Newspaper className="h-3.5 w-3.5" />
        </div>
        <h2 className="text-sm font-semibold text-white">Bitcoin news &amp; sentiment</h2>
      </div>
      <div className="my-auto rounded-2xl border border-[#263d32] bg-[#0c1310] p-4">
        <p className="text-sm font-medium text-white">Verified news feed not configured</p>
        <p className="mt-2 text-xs leading-relaxed text-[#7f9389]">
          This dashboard has no connected news provider. Headlines, source citations, and bullish
          or bearish impact are intentionally not displayed rather than invented or presented as
          live reporting.
        </p>
      </div>
      <p className="mt-3 text-[10px] leading-relaxed text-[#7f9389]">
        News sentiment is not part of the current paper-trading decision engine.
      </p>
    </section>
  );
}
