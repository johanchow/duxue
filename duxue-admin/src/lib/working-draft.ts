import { randomUUID } from 'node:crypto';
import type { PoolClient } from 'pg';
import { audit } from './db';

/** Serialize all administrators onto one environment-wide pending snapshot. */
export async function workingDraft(
  client: Pick<PoolClient, 'query'>,
  input: {
    actorId: string;
    bundle: unknown;
    baseRelease: string | null;
    resolveBase?: (
      client: Pick<PoolClient, 'query'>,
    ) => Promise<{ bundle: unknown; baseRelease: string | null }>;
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
  if (current) return { draft: current, created: false };
  const base = input.resolveBase ? await input.resolveBase(client) : input;
  const id = randomUUID();
  const draft = (
    await client.query(
      "INSERT INTO agent_drafts(id,title,bundle,base_bundle,base_release_id,created_by,state) VALUES($1,'当前待发布配置',$2,$2,$3,$4,'working') RETURNING *",
      [id, base.bundle, base.baseRelease, input.actorId],
    )
  ).rows[0];
  await audit(client, input.actorId, 'draft.create', id);
  return { draft, created: true };
}
