import { handle } from '@/lib/api';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 300;
type Context = { params: Promise<{ path: string[] }> };
async function route(request: Request, context: Context) {
  return handle(request, (await context.params).path);
}
export { route as GET, route as POST, route as PUT, route as DELETE };
