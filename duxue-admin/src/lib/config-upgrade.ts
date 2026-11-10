import type { PoolClient } from 'pg';
import { audit } from './db';
import { workingDraft } from './working-draft';

export type UpgradeSource = {
  id: string;
  digest: string;
  kind: 'release' | 'draft';
  revision?: number;
};

/** Guard against applying an offline upgrade to a configuration changed since export. */
export function assertUpgradeSource(
  source: UpgradeSource,
  currentDraft: { id: string; revision: number } | undefined,
  release: { id: string; digest: string } | undefined,
) {
  if (source.kind === 'draft') {
    if (
      !currentDraft ||
      currentDraft.id !== source.id ||
      currentDraft.revision !== source.revision
    )
      throw new Error('草稿已变化，请重新导出并升级；不会覆盖未发布修改');
  } else if (source.kind === 'release') {
    if (currentDraft)
      throw new Error('存在工作草稿，请导出该草稿升级，不能覆盖');
    if (
      !release ||
      release.id !== source.id ||
      release.digest !== source.digest
    )
      throw new Error('发布基线已变化，请重新导出并升级');
  } else throw new Error('未知升级来源');
}

export async function importConfigUpgrade(
  client: Pick<PoolClient, 'query'>,
  input: {
    source: UpgradeSource;
    bundle: unknown;
    actorId: string;
    environment: string;
  },
) {
  await client.query(
    "SELECT pg_advisory_xact_lock(hashtext('agent-working-draft'))",
  );
  const current = (
    await client.query(
      "SELECT * FROM agent_drafts WHERE state='working' FOR UPDATE",
    )
  ).rows[0];
  const release = (
    await client.query(
      'SELECT r.id,r.digest,r.bundle FROM agent_environments e JOIN agent_releases r ON r.id=e.release_id WHERE e.name=$1 FOR UPDATE OF e',
      [input.environment],
    )
  ).rows[0];
  assertUpgradeSource(input.source, current, release);
  const draft =
    current ||
    (
      await workingDraft(client, {
        actorId: input.actorId,
        bundle: release.bundle,
        baseRelease: release.id,
      })
    ).draft;
  // Preserve original base_bundle/base_release_id so existing publish checks still apply.
  await client.query(
    'UPDATE agent_drafts SET bundle=$1,revision=revision+1,validation=NULL,updated_at=now() WHERE id=$2',
    [input.bundle, draft.id],
  );
  await audit(client, input.actorId, 'draft.import-upgrade', draft.id, {
    source: input.source,
  });
  return draft.id;
}
