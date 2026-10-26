import { NextRequest } from 'next/server';
import { proxyBackend } from '../../_lib/backend';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  return proxyBackend(`/api/memory/episodes${request.nextUrl.search}`);
}
