import { NextResponse } from 'next/server';

export async function proxyBackend(path: string, init?: RequestInit) {
  try {
    const response = await fetch(`http://localhost:8000${path}`, {
      ...init,
      cache: 'no-store',
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    console.error(`Mortis backend request failed for ${path}:`, error);
    return NextResponse.json(
      { detail: 'Mortis paper-trading backend is unavailable. Start server.py and retry.' },
      { status: 503 },
    );
  }
}
