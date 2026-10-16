import { proxyBackend } from '../../_lib/backend';

export async function POST() {
  return proxyBackend('/api/trades/close', { method: 'POST' });
}
