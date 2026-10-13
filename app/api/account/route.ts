import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1200);
    // Forward request to Python backend
    const response = await fetch('http://localhost:8000/api/account', {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: controller.signal,
      cache: 'no-store',
    });
    clearTimeout(timeoutId);

    if (response.ok) {
      const data = await response.json();
      return NextResponse.json(data);
    }
  } catch (_error) {
    // Return mock data if backend is unavailable
  }

  return NextResponse.json({
    equity: 10340.50,
    starting_equity: 10000.00,
    total_return_pct: 3.41,
    unrealized_pnl_usd: 125.40,
    open_position: {
      side: 'long',
      size: 0.25,
      entry: 80920.00,
      fees_paid_open: 8.50
    },
    last_5_closed_trades: [
      { id: 'tr_1', side: 'long', pnl_usd: 145.20, pnl_pct: 1.45, exit_time: new Date(Date.now() - 3600000).toISOString() },
      { id: 'tr_2', side: 'short', pnl_usd: 85.00, pnl_pct: 0.85, exit_time: new Date(Date.now() - 7200000).toISOString() },
      { id: 'tr_3', side: 'long', pnl_usd: -42.00, pnl_pct: -0.42, exit_time: new Date(Date.now() - 14400000).toISOString() }
    ],
    total_trades: 14,
    win_rate: 71.4,
    today_realized_pnl_usd: 340.50,
    is_blocked: false,
    block_reason: null,
    current_btc_price: 81420.50
  });
}