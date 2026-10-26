import { NextRequest } from 'next/server';
import { proxyBackend } from '../_lib/backend';

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: 'Request body must be valid JSON.' }, { status: 400 });
  }
  if (!isJsonObject(body)) {
    return Response.json({ detail: 'Request body must be a JSON object.' }, { status: 400 });
  }
  return proxyBackend('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, execute: body.execute === true }),
  });
}
