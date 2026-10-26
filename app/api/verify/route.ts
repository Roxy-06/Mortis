import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: 'Request body must be valid JSON.' }, { status: 400 });
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return NextResponse.json({ detail: 'Request body must be a JSON object.' }, { status: 400 });
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 1500);
  try {
    const response = await fetch('http://localhost:8000/api/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const payload: unknown = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    console.error('Mortis verification backend is unavailable:', error);
    return NextResponse.json(
      {
        valid: false,
        status: 'backend_unavailable',
        detail: 'Decision verification requires the Python backend.',
      },
      { status: 503 },
    );
  } finally {
    clearTimeout(timeoutId);
  }
}
