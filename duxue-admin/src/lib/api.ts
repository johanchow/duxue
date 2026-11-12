import { evaluationResponse } from './evaluation-api';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { pool, transaction, audit } from './db';
import {
  ApiError,
  checkOrigin,
  requireUser,
  authorize,
  login,
  hash,
  sessionToken,
} from './auth';
import { config } from './config';
import { serverCall } from './server';
import { requiredDebugComponents } from './release-evidence';
import { workingDraft } from './working-draft';
import { requireUnchangedWorkflows } from './workflow-policy';

const uuid = (value: unknown) =>
  typeof value === 'string' &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
function assert(value: unknown, message: string, status = 400): asserts value {
  if (!value) throw new ApiError(status, message);
}
async function bodyOf(request: Request) {
  const text = await request.text();
  assert(text.length < 1000000, '请求内容过大', 413);
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    throw new ApiError(400, 'JSON格式错误');
  }
}
async function draftById(id: string) {
  assert(uuid(id), '草稿编号无效');
  const result = await pool().query('SELECT * FROM agent_drafts WHERE id=$1', [
    id,
  ]);
  assert(result.rows[0], '草稿不存在', 404);
  return result.rows[0];
}
async function executeDebug(
  draft: any,
  input: any,
  actorId: string,
  sourceKind: 'draft' | 'release',
) {
  assert(
    typeof input?.content === 'string' && input.content.length > 0,
    '请输入调试内容',
  );
  const validation = await serverCall('validate', {
      bundle: draft.bundle,
    }),
    id = randomUUID();
  await pool().query(
    "INSERT INTO agent_debug_runs(id,draft_id,revision,digest,input,status,created_by,base_release_id,source_kind,target_kind,target_id,bundle) VALUES($1,$2,$3,$4,$5,'running',$6,$7,$8,$9,$10,$11)",
    [
      id,
      draft.id,
      draft.revision,
      validation.digest,
      input,
      actorId,
      draft.base_release_id,
      sourceKind,
      input.target_kind || null,
      input.target_id || null,
      draft.bundle,
    ],
  );
  try {
    const result = await serverCall('debug', {
      bundle: draft.bundle,
      input: input,
    });
    assert(result.digest === validation.digest, '调试配置摘要不一致', 502);
    await transaction(async (client) => {
      await client.query(
        'UPDATE agent_debug_runs SET status=$1,result=$2,finished_at=now() WHERE id=$3',
        [result.status, result, id],
      );
      await audit(client, actorId, 'debug.complete', draft.id, {
        run_id: id,
        revision: draft.revision,
        status: result.status,
      });
    });
    return Response.json({
      id,
      ...result,
      source: {
        kind: sourceKind,
        release_id: sourceKind === 'release' ? draft.base_release_id : null,
        draft_id: draft.id,
        revision: draft.revision,
        digest: validation.digest,
      },
    });
  } catch (error) {
    await pool().query(
      "UPDATE agent_debug_runs SET status='failed',error=$1,finished_at=now() WHERE id=$2",
      [(error as Error).message.slice(0, 300), id],
    );
    throw error;
  }
}
export async function handle(request: Request, parts: string[]) {
  try {
    const method = request.method,
      key = parts.join('/'),
      environmentName = config().environment;
    if (key === 'health' && method === 'GET') {
      try {
        await pool().query('SELECT 1');
        return Response.json({ status: 'ok', environment: environmentName });
      } catch {
        return Response.json({ status: 'unavailable' }, { status: 503 });
      }
    }
    if (parts[0] === 'internal') {
      const expected = Buffer.from('Bearer ' + config().token),
        actual = Buffer.from(request.headers.get('authorization') || '');
      assert(
        expected.length === actual.length && timingSafeEqual(expected, actual),
        '内部鉴权失败',
        401,
      );
      if (key === 'internal/release' && method === 'GET') {
        const result = await pool().query(
          'SELECT e.generation,r.id,r.digest,r.bundle FROM agent_environments e LEFT JOIN agent_releases r ON r.id=e.release_id WHERE e.name=$1',
          [environmentName],
        );
        const row = result.rows[0];
        return Response.json({
          environment: environmentName,
          generation: row.generation,
          release: row.id
            ? { id: row.id, digest: row.digest, bundle: row.bundle }
            : null,
        });
      }
      if (key === 'internal/ack' && method === 'POST') {
        const data = await bodyOf(request);
        assert(
          typeof data.instance_id === 'string' &&
            data.instance_id.length <= 128,
          '实例编号无效',
        );
        assert(['loaded', 'failed'].includes(data.status), '回执状态无效');
        assert(
          data.release_id === null || uuid(data.release_id),
          '版本编号无效',
        );
        if (data.release_id) {
          const r = await pool().query(
            'SELECT digest FROM agent_releases WHERE id=$1',
            [data.release_id],
          );
          assert(r.rows[0]?.digest === data.digest, '回执摘要不匹配');
        }
        await pool().query(
          'INSERT INTO agent_server_instances(instance_id,release_id,digest,status,error) VALUES($1,$2,$3,$4,$5) ON CONFLICT(instance_id) DO UPDATE SET release_id=excluded.release_id,digest=excluded.digest,status=excluded.status,error=excluded.error,last_seen=now()',
          [
            data.instance_id,
            data.release_id,
            data.digest,
            data.status,
            typeof data.error === 'string' ? data.error.slice(0, 200) : null,
          ],
        );
        return Response.json({ accepted: true });
      }
      throw new ApiError(404, '接口不存在');
    }
    if (method !== 'GET') checkOrigin(request);
    if (key === 'session' && method === 'POST') {
      const data = await bodyOf(request);
      assert(
        typeof data.email === 'string' &&
          data.email.length < 255 &&
          typeof data.password === 'string' &&
          data.password.length <= 200,
        '请输入邮箱和密码',
      );
      const token = await login(data.email, data.password);
      assert(token, '邮箱或密码错误', 401);
      return Response.json(
        { authenticated: true },
        {
          headers: {
            'Set-Cookie': `duxue_admin_session=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200${(process.env.ADMIN_PUBLIC_ORIGIN || request.url).startsWith('https:') ? '; Secure' : ''}`,
          },
        },
      );
    }
    const user = await requireUser(request);
    authorize(user, method, parts);
    if (parts[0] === 'evaluation') return evaluationResponse(request, parts);
    if (key === 'session' && method === 'GET') return Response.json(user);
    if (key === 'session' && method === 'DELETE') {
      await pool().query('DELETE FROM admin_sessions WHERE token_hash=$1', [
        hash(sessionToken(request)!),
      ]);
      return Response.json(
        { ok: true },
        {
          headers: {
            'Set-Cookie':
              'duxue_admin_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',
          },
        },
      );
    }
    if (key === 'state' && method === 'GET') {
      await pool().query(
        "UPDATE agent_debug_runs SET status='interrupted',error='运行超过恢复窗口，结果未知',finished_at=now() WHERE status='running' AND started_at<now()-interval '10 minutes'",
      );
      const [drafts, releases, runs, environment, instances] =
        await Promise.all([
          pool().query(
            "SELECT id,title,revision,validation,updated_at,base_release_id,bundle,base_bundle,bundle->>'format_version' AS format_version FROM agent_drafts WHERE state='working'",
          ),
          pool().query(
            "SELECT id,sequence,digest,draft_id,revision,created_at,bundle->>'format_version' AS format_version,bundle->>'compatibility' AS compatibility FROM agent_releases WHERE bundle->>'format_version'='3' ORDER BY sequence DESC LIMIT 50",
          ),
          pool().query(
            "SELECT run.id,run.draft_id,run.revision,run.digest,run.input,run.status,run.error,run.started_at,run.finished_at,run.base_release_id,run.source_kind,run.target_kind,run.target_id,run.result->'covered_components' AS covered_components,r.sequence AS base_sequence FROM agent_debug_runs run LEFT JOIN agent_releases r ON r.id=run.base_release_id WHERE run.format_version=3 ORDER BY run.started_at DESC LIMIT 50",
          ),
          pool().query('SELECT * FROM agent_environments WHERE name=$1', [
            environmentName,
          ]),
          pool().query(
            'SELECT * FROM agent_server_instances ORDER BY last_seen DESC LIMIT 50',
          ),
        ]);
      let catalog = null,
        catalogError = null;
      try {
        const active = (
          await pool().query(
            'SELECT r.id,r.sequence,r.bundle FROM agent_environments e JOIN agent_releases r ON r.id=e.release_id WHERE e.name=$1',
            [environmentName],
          )
        ).rows[0];
        const sourceBundle = active?.bundle || drafts.rows[0]?.bundle;
        assert(
          sourceBundle,
          '管理库尚无配置，请先使用config:import导入完整配置快照',
          409,
        );
        catalog = await serverCall('catalog', { bundle: sourceBundle });
        if (active) {
          for (const [file, definition] of Object.entries(
            active.bundle.files,
          ) as [string, any][]) {
            if (file.startsWith('workflows/'))
              catalog.workflows[definition.id] = definition;
            if (['agent', 'gate', 'tool'].includes(definition.kind))
              catalog.definitions[definition.id] = definition;
          }
          for (const component of catalog.components) {
            const definition = catalog.definitions[component.id];
            component.name = definition.display_name || component.name;
            component.description =
              definition.description || component.description;
          }
          catalog.source = 'admin-release';
          catalog.source_release = { id: active.id, sequence: active.sequence };
        }
      } catch (error) {
        catalogError = (error as Error).message;
      }
      return Response.json({
        user,
        drafts: drafts.rows.map(({ bundle, base_bundle, ...row }) => ({
          ...row,
          required_components: requiredDebugComponents(
            bundle,
            base_bundle || bundle,
          ),
          changed_ids: Object.entries(bundle.files)
            .filter(
              ([file, value]) =>
                JSON.stringify(value) !==
                JSON.stringify(base_bundle?.files[file]),
            )
            .map(([, value]: any) => value.id)
            .filter(Boolean),
        })),
        releases: releases.rows,
        runs: runs.rows,
        environment: environment.rows[0],
        instances: instances.rows,
        catalog,
        catalogError,
      });
    }
    if (key === 'drafts' && method === 'POST') {
      await bodyOf(request);
      const existing = (
        await pool().query("SELECT * FROM agent_drafts WHERE state='working'")
      ).rows[0];
      if (existing) return Response.json(existing);
      const published = (
        await pool().query(
          'SELECT r.bundle FROM agent_environments e JOIN agent_releases r ON r.id=e.release_id WHERE e.name=$1',
          [environmentName],
        )
      ).rows[0];
      assert(published, '没有已发布配置，请先导入Admin配置快照', 409);
      const defaults = published.bundle;
      await serverCall('validate', { bundle: defaults });
      const result = await transaction((client) =>
        workingDraft(client, {
          actorId: user.id,
          bundle: defaults,
          baseRelease: null,
          resolveBase: async (connection) => {
            const active = (
              await connection.query(
                'SELECT r.id,r.bundle FROM agent_environments e JOIN agent_releases r ON r.id=e.release_id WHERE e.name=$1',
                [environmentName],
              )
            ).rows[0];
            if (active)
              assert(
                active.bundle.compatibility === defaults.compatibility,
                '当前发布与代码不兼容，需先完成配置升级',
                409,
              );
            return {
              bundle: active?.bundle || defaults,
              baseRelease: active?.id || null,
            };
          },
        }),
      );
      return Response.json(result.draft, {
        status: result.created ? 201 : 200,
      });
    }
    if (
      parts[0] === 'releases' &&
      uuid(parts[1]) &&
      parts[2] === 'debug' &&
      method === 'POST'
    ) {
      const release = (
        await pool().query('SELECT * FROM agent_releases WHERE id=$1', [
          parts[1],
        ])
      ).rows[0];
      assert(release, '发布不存在', 404);
      const data = await bodyOf(request);
      return executeDebug(
        { ...release, id: release.draft_id, base_release_id: release.id },
        data.input,
        user.id,
        'release',
      );
    }
    if (parts.length === 3 && parts[2] === 'snapshot' && method === 'GET') {
      assert(uuid(parts[1]), '配置编号无效');
      if (parts[0] === 'releases') {
        const row = (
          await pool().query(
            'SELECT id,sequence,digest,bundle FROM agent_releases WHERE id=$1',
            [parts[1]],
          )
        ).rows[0];
        assert(row, '发布不存在', 404);
        return Response.json(
          { ...row, kind: 'release', environment: environmentName },
          {
            headers: {
              'Content-Disposition': `attachment; filename="agent-release-R${row.sequence}.json"`,
            },
          },
        );
      }
      if (parts[0] === 'drafts') {
        const row = await draftById(parts[1]);
        const validation = await serverCall('validate', { bundle: row.bundle });
        return Response.json(
          {
            id: row.id,
            revision: row.revision,
            digest: validation.digest,
            bundle: row.bundle,
            kind: 'draft',
            environment: environmentName,
          },
          {
            headers: {
              'Content-Disposition': `attachment; filename="agent-draft-${row.id}-${row.revision}.json"`,
            },
          },
        );
      }
    }
    if (parts[0] === 'drafts' && parts[1]) {
      const draft = await draftById(parts[1]);
      if (parts.length === 2 && method === 'GET') return Response.json(draft);
      const data = await bodyOf(request);
      assert(
        draft.state === 'working',
        '此修改已发布或归档，请打开当前待发布配置',
        409,
      );
      assert(data.revision === draft.revision, '草稿已变化，请重新加载', 409);
      if (parts.length === 2 && method === 'PUT') {
        assert(
          data.bundle && JSON.stringify(data.bundle).length < 800000,
          '配置包无效',
        );
        requireUnchangedWorkflows(data.bundle, draft.base_bundle);
        const saved = await transaction(async (client) => {
          const result = await client.query(
            "UPDATE agent_drafts SET bundle=$1,title=$2,revision=revision+1,validation=NULL,updated_at=now() WHERE id=$3 AND revision=$4 AND state='working' RETURNING *",
            [
              data.bundle,
              String(data.title || draft.title).slice(0, 100),
              draft.id,
              data.revision,
            ],
          );
          assert(result.rows[0], '草稿已变化，请重新加载', 409);
          await audit(client, user.id, 'draft.save', draft.id, {
            revision: result.rows[0].revision,
          });
          return result.rows[0];
        });
        return Response.json(saved);
      }
      if (parts[2] === 'discard' && method === 'POST') {
        await transaction(async (client) => {
          const result = await client.query(
            "UPDATE agent_drafts SET state='archived' WHERE id=$1 AND revision=$2 AND state='working' RETURNING id",
            [draft.id, draft.revision],
          );
          assert(result.rows[0], '修改已变化，请刷新后重试', 409);
          await audit(client, user.id, 'draft.discard', draft.id);
        });
        return Response.json({ ok: true });
      }
      if (parts[2] === 'validate' && method === 'POST') {
        const validation = await serverCall('validate', {
          bundle: draft.bundle,
        });
        const result = await pool().query(
          "UPDATE agent_drafts SET validation=$1 WHERE id=$2 AND revision=$3 AND state='working' RETURNING id",
          [validation, draft.id, draft.revision],
        );
        assert(result.rows[0], '校验期间草稿已变化', 409);
        return Response.json(validation);
      }
      if (parts[2] === 'debug' && method === 'POST') {
        return executeDebug(draft, data.input, user.id, 'draft');
      }
      if (parts[2] === 'publish' && method === 'POST') {
        requireUnchangedWorkflows(draft.bundle, draft.base_bundle);
        const validation = await serverCall('validate', {
          bundle: draft.bundle,
        });
        assert(
          validation.runtime_ready === true,
          '运行协议未就绪，请完成配置升级后再发布',
          409,
        );
        const release = await transaction(async (client) => {
          const locked = (
            await client.query(
              'SELECT * FROM agent_drafts WHERE id=$1 FOR UPDATE',
              [draft.id],
            )
          ).rows[0];
          assert(
            locked.revision === draft.revision && locked.state === 'working',
            '发布期间草稿已变化',
            409,
          );
          const env = (
            await client.query(
              'SELECT * FROM agent_environments WHERE name=$1 FOR UPDATE',
              [environmentName],
            )
          ).rows[0];
          assert(
            String(data.generation) === String(env.generation),
            '环境版本已变化，请刷新后重试',
            409,
          );
          assert(
            locked.base_release_id === env.release_id,
            '当前发布已变化，请先重新整理待发布修改',
            409,
          );
          assert(
            env.release_id === null ||
              JSON.stringify(locked.bundle) !==
                JSON.stringify(locked.base_bundle),
            '没有待发布的修改',
            409,
          );
          const evidence = (
            await client.query(
              "SELECT id,result FROM agent_debug_runs WHERE draft_id=$1 AND revision=$2 AND digest=$3 AND status='succeeded' ORDER BY finished_at DESC",
              [draft.id, draft.revision, validation.digest],
            )
          ).rows;
          const debug = evidence[0];
          const covered = new Set(
            evidence.flatMap((row) => row.result?.covered_components || []),
          );
          const missing = requiredDebugComponents(
            draft.bundle,
            draft.base_bundle || draft.bundle,
          ).filter((unit) => !covered.has(unit));
          assert(
            !missing.length,
            '以下模型需完成同修订真实调试：' + missing.join('、'),
            409,
          );
          const id = randomUUID();
          await client.query(
            'INSERT INTO agent_releases(id,draft_id,revision,digest,bundle,validation,debug_run_id,created_by) VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(draft_id,revision,digest) DO NOTHING',
            [
              id,
              draft.id,
              draft.revision,
              validation.digest,
              draft.bundle,
              validation,
              debug?.id || null,
              user.id,
            ],
          );
          const row = (
            await client.query(
              'SELECT id,sequence,digest FROM agent_releases WHERE draft_id=$1 AND revision=$2 AND digest=$3',
              [draft.id, draft.revision, validation.digest],
            )
          ).rows[0];
          await client.query(
            'UPDATE agent_environments SET release_id=$1,generation=generation+1,updated_at=now() WHERE name=$2',
            [row.id, environmentName],
          );
          await client.query(
            "UPDATE agent_drafts SET state='published' WHERE id=$1",
            [draft.id],
          );
          await audit(client, user.id, 'release.publish', row.id, {
            draft_id: draft.id,
            revision: draft.revision,
          });
          return row;
        });
        return Response.json(release);
      }
    }
    if (parts[0] === 'runs' && method === 'GET' && uuid(parts[1])) {
      const row = (
        await pool().query('SELECT * FROM agent_debug_runs WHERE id=$1', [
          parts[1],
        ])
      ).rows[0];
      assert(row, '调试记录不存在', 404);
      return Response.json(row);
    }
    if (parts[0] === 'releases' && uuid(parts[1])) {
      const release = (
        await pool().query('SELECT * FROM agent_releases WHERE id=$1', [
          parts[1],
        ])
      ).rows[0];
      assert(release, '版本不存在', 404);
      if (method === 'GET' && parts[2] === 'detail')
        return Response.json(release);
      if (method === 'GET')
        return Response.json(release.bundle, {
          headers: {
            'Content-Disposition': `attachment; filename="agents-R${release.sequence}.json"`,
          },
        });
      if (parts[2] === 'rollback' && method === 'POST') {
        const data = await bodyOf(request);
        const validation = await serverCall('validate', {
          bundle: release.bundle,
        });
        assert(
          validation.runtime_ready === true,
          '该版本不支持当前运行协议，不能回滚',
          409,
        );
        await transaction(async (client) => {
          const env = (
            await client.query(
              'SELECT * FROM agent_environments WHERE name=$1 FOR UPDATE',
              [environmentName],
            )
          ).rows[0];
          assert(
            String(data.generation) === String(env.generation),
            '环境版本已变化，请刷新',
            409,
          );
          await client.query(
            'UPDATE agent_environments SET release_id=$1,generation=generation+1,updated_at=now() WHERE name=$2',
            [release.id, environmentName],
          );
          await audit(client, user.id, 'release.rollback', release.id);
        });
        return Response.json({ ok: true });
      }
    }
    throw new ApiError(404, '接口不存在');
  } catch (error) {
    if (error instanceof ApiError)
      return Response.json({ error: error.message }, { status: error.status });
    if ((error as { code?: string }).code === '23505')
      return Response.json(
        { error: '已有进行中的调试，请完成后再试' },
        { status: 409 },
      );
    console.error(
      'admin operation failed',
      (error as { code?: string })?.code || (error as Error).name,
    );
    return Response.json(
      { error: '操作未完成，请检查服务连接和配置' },
      { status: 500 },
    );
  }
}
