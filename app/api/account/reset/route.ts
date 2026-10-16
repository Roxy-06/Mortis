import { proxyBackend } from '../../_lib/backend';

export async function POST() {
  return proxyBackend('/api/account/reset', { method: 'POST' });
}
