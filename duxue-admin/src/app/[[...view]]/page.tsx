import { Suspense } from 'react';
import { redirect } from 'next/navigation';
import Studio from '@/components/studio';
export const dynamic = 'force-dynamic';
export default async function Page({
  params,
}: {
  params: Promise<{ view?: string[] }>;
}) {
  const { view } = await params;
  if (!view?.length) redirect('/workflows');
  return (
    <Suspense fallback={<div className="loading">正在加载 Agent Studio…</div>}>
      <Studio />
    </Suspense>
  );
}
