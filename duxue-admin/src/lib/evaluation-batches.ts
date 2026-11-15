/** Read-only projections of Langfuse records. No semantic inference from text. */
export type Doc = Record<string, any>;
export const statusLabels: Record<string, string> = {
  pass: '✅ 通过',
  fail: '❌ 不通过',
  error: '⚠️ 异常',
  not_run: '⏸️ 未执行',
  unknown: '⚠️ 缺少有效结果',
};
export function document(value: unknown): Doc {
  const parsed = typeof value === 'string' ? JSON.parse(value) : value;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    throw new Error('Langfuse执行数据不是有效对象');
  return parsed as Doc;
}
export function groupBatches(experiments: Doc[]) {
  const groups = new Map<string, Doc>();
  for (const e of experiments) {
    const key = e.metadata?.run_id || `experiment:${e.id}`;
    if (!groups.has(key))
      groups.set(key, {
        id: key,
        startTime: e.startTime,
        experiments: [],
        expectedCases: Number(e.metadata?.case_count) || null,
        configDigest: e.metadata?.config_digest || null,
        graderVersion: e.metadata?.grader_version || null,
        codeVersion: e.metadata?.git_commit || null,
        codeDigest: e.metadata?.code_digest || null,
      });
    const batch = groups.get(key)!;
    batch.experiments.push(e);
    if (e.startTime > batch.startTime) batch.startTime = e.startTime;
    if (
      batch.configDigest !== (e.metadata?.config_digest || null) ||
      batch.graderVersion !== (e.metadata?.grader_version || null) ||
      batch.codeVersion !== (e.metadata?.git_commit || null) ||
      batch.codeDigest !== (e.metadata?.code_digest || null) ||
      batch.expectedCases !== (Number(e.metadata?.case_count) || null)
    )
      batch.identityConflict = true;
  }
  return [...groups.values()].sort((a, b) =>
    b.startTime.localeCompare(a.startTime),
  );
}
export function caseProjection(item: Doc) {
  const input = item.input == null ? {} : document(item.input),
    output = item.output == null ? {} : document(item.output),
    expected = item.expectedOutput == null ? {} : document(item.expectedOutput);
  const scores = (item.scores || []).filter(
    (s: Doc) =>
      s.name === 'eval.status' &&
      s.source === 'API' &&
      s.subject?.id === item.id,
  );
  const status =
    input.record?.id &&
    Array.isArray(input.record?.checks) &&
    expected.checks &&
    item.output != null &&
    (item.scores || []).length < 20 &&
    scores.length === 1 &&
    Object.hasOwn(statusLabels, scores[0].value)
      ? scores[0].value
      : 'unknown';
  const record = input.record || {};
  // A completed observation's output is immutable; resume may have updated scores.
  const snapshotCurrent = status === output.status;
  const checks = (record.checks || []).map((r: Doc) => ({
    check_id: r.id,
    status: 'unknown',
    ...(output.checks || []).find((c: Doc) => c.check_id === r.id),
    component: r.component || 'unknown',
    requirement: expected.checks?.[r.id] || {},
  }));
  return {
    id: item.experimentItemId,
    observationId: item.id,
    traceId: item.traceId,
    experimentId: item.experimentId,
    experimentName: item.experimentName,
    caseId: record.id || output.case_id || item.experimentItemId,
    category: item.experimentItemMetadata?.category || null,
    calibration: record.type === 'judge',
    status,
    snapshotCurrent,
    checks,
    input,
    expected,
    output,
    url: item.url,
    components: [...new Set(checks.map((c: Doc) => c.component))],
    labelStatus: item.experimentItemMetadata?.label_status || 'unknown',
    failedDimensions: snapshotCurrent
      ? [
          ...new Set(
            checks.flatMap((c: Doc) =>
              (c.grades || [])
                .filter((g: Doc) => g.status !== 'pass')
                .map((g: Doc) => g.name),
            ),
          ),
        ]
      : [],
    firstFailure: snapshotCurrent
      ? checks.find((c: Doc) => ['fail', 'error'].includes(c.status))?.check_id
      : null,
  };
}
export function checkpointGrades(check: Doc, scores: Doc[]) {
  return Object.entries(check.requirement?.evaluators || {}).map(
    ([name, threshold]) => {
      const rule = threshold as Doc;
      const found = scores.filter(
        (s) =>
          s.name === name &&
          s.source === 'EVAL' &&
          s.subject?.id === check.observation_id,
      );
      const s = found[0],
        value = s?.value;
      const validRule =
        Object.keys(rule).length === 1 &&
        ((Number.isInteger(rule.min) && rule.min >= 1 && rule.min <= 5) ||
          typeof rule.equals === 'boolean');
      const valid =
        validRule &&
        found.length === 1 &&
        (rule.min !== undefined
          ? typeof value === 'number' &&
            Number.isInteger(value) &&
            value >= 1 &&
            value <= 5
          : typeof value === 'boolean' ||
            (typeof value === 'number' && (value === 0 || value === 1)));
      const passed =
        rule.min !== undefined
          ? value >= rule.min
          : Boolean(value) === rule.equals;
      return {
        name,
        value,
        threshold:
          rule.min !== undefined ? `≥${rule.min}/5` : String(rule.equals),
        status:
          !valid || check.wrong_versions?.includes(name)
            ? 'error'
            : passed
              ? 'pass'
              : 'fail',
        comment: s?.comment || '未提供有效裁判理由',
        metadata: s?.metadata,
      };
    },
  );
}
const counts = (rows: Doc[]) =>
  Object.fromEntries(
    Object.keys(statusLabels).map((s) => [
      s,
      rows.filter((r) => r.status === s).length,
    ]),
  );
export function batchProjection(batch: Doc, items: Doc[]) {
  const unique = new Set();
  for (const item of items) {
    if (unique.has(item.experimentItemId))
      throw new Error('同批次出现重复Dataset Item');
    unique.add(item.experimentItemId);
  }
  const cases = items.map(caseProjection);
  const checks = cases.flatMap((c) =>
    c.checks.map((check: Doc) =>
      c.snapshotCurrent ? check : { ...check, status: 'unknown' },
    ),
  );
  const components: Doc[] = [];
  for (const component of new Set(checks.map((c) => c.component))) {
    const subset = checks.filter((c) => c.component === component);
    components.push({
      id: component,
      ...counts(subset),
      planned: subset.length,
      executed: subset.filter(
        (c) => c.observation_id || ['pass', 'fail', 'error'].includes(c.status),
      ).length,
    });
  }
  const calls = checks.flatMap((c) => c.execution_summary || []);
  const runtime = [...new Set(calls.map((c) => c.component_id))].map((id) => {
    const subset = calls.filter((c) => c.component_id === id);
    return {
      id,
      calls: subset.length,
      errors: subset.filter((c) => c.status === 'failed').length,
      durationMs: subset.reduce((n, c) => n + (c.duration_ms || 0), 0),
      tokensIn: subset.every((c) => Number.isFinite(c.tokens_in))
        ? subset.reduce((n, c) => n + c.tokens_in, 0)
        : null,
      tokensOut: subset.every((c) => Number.isFinite(c.tokens_out))
        ? subset.reduce((n, c) => n + c.tokens_out, 0)
        : null,
    };
  });
  return {
    ...batch,
    cases,
    counts: counts(cases),
    application: counts(cases.filter((c) => !c.calibration)),
    calibration: counts(cases.filter((c) => c.calibration)),
    checkpoints: counts(checks),
    components,
    runtime,
    complete:
      !batch.identityConflict &&
      batch.expectedCases !== null &&
      cases.length === batch.expectedCases,
  };
}
function canonical(value: any): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object')
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`)
      .join(',')}}`;
  return JSON.stringify(value);
}
export function compareBatches(current: Doc, baseline: Doc) {
  if (
    !current.complete ||
    !baseline.complete ||
    !current.codeVersion ||
    !baseline.codeVersion ||
    !current.configDigest ||
    !baseline.configDigest ||
    !current.graderVersion ||
    current.graderVersion !== baseline.graderVersion
  )
    return {
      comparable: false,
      reason: '批次不完整、配置/代码身份缺失或裁判版本不同，不能判断回归。',
    };
  const old = new Map(baseline.cases.map((c: Doc) => [c.id, c]));
  if (
    current.cases.length !== old.size ||
    current.cases.some((c: Doc) => {
      const b = old.get(c.id) as Doc | undefined;
      return (
        !b ||
        canonical(c.input) !== canonical(b.input) ||
        canonical(c.expected) !== canonical(b.expected)
      );
    })
  )
    return {
      comparable: false,
      reason: '用例、输入或判分要求不一致，不能判断回归。',
    };
  return {
    comparable: true,
    changes: current.cases.map((c: Doc) => {
      const b = old.get(c.id) as Doc;
      return {
        id: c.id,
        caseId: c.caseId,
        before: b.status,
        after: c.status,
        change:
          !['pass', 'fail'].includes(c.status) ||
          !['pass', 'fail'].includes(b.status)
            ? 'incomplete'
            : b.status === 'pass' && c.status === 'fail'
              ? 'regression'
              : b.status === 'fail' && c.status === 'pass'
                ? 'fixed'
                : 'unchanged',
      };
    }),
  };
}
