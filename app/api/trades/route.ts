import { NextRequest } from 'next/server';
import { proxyBackend } from '../_lib/backend';

export const dynamic = 'force-dynamic';

export async function GET() {
  return proxyBackend('/api/trades');
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: 'Request body must be valid JSON.' }, { status: 400 });
  }
  return proxyBackend('/api/trades', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
