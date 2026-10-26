import { proxyBackend } from '../../_lib/backend';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: Request,
  { params }: { params: { tradeId: string } },
) {
  return proxyBackend(`/api/trades/${encodeURIComponent(params.tradeId)}`);
}
