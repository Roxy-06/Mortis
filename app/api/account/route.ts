import { proxyBackend } from '../_lib/backend';

export const dynamic = 'force-dynamic';

export async function GET() {
  return proxyBackend('/api/account');
}
