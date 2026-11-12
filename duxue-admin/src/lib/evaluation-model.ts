/** Business metric contract. No Langfuse credentials or result persistence. */
export type Row = Record<string, any>;
export type MetricUnit = 'points' | 'percent' | 'seconds' | 'usd';
export const metricPolicy = [
  {
    id: 'overall',
    label: 'Overall Score',
    score: 'eval.overall',
    unit: 'points',
    range: [0, 100],
    scale: 1,
    description: '任务级综合分均值；尚无业务权重时不自动生成。',
  },
  {
    id: 'task_success',
    label: 'Task Success',
    score: 'eval.task_success',
    unit: 'percent',
    range: [0, 1],
    scale: 100,
    description: '必需要求全部满足的任务比例；运行成功或门禁放行不能替代。',
  },
  {
    id: 'teaching_correctness',
    label: 'Teaching Correctness',
    score: 'eval.teaching_correctness',
    unit: 'percent',
    range: [1, 5],
    scale: 20,
    description: '检查点教学正确性评分均值 / 5 × 100；当前仍需人工校准。',
  },
  {
    id: 'guidance_logic',
    label: 'Guidance Logic',
    score: 'eval.guidance_logic',
    unit: 'percent',
    range: [1, 5],
    scale: 20,
    description:
      '检查点引导逻辑性评分均值 / 5 × 100；与知识正确性独立，仍需人工校准。',
  },
  {
    id: 'answer_protection',
    label: 'Answer Protection',
    score: 'eval.answer_protection',
    unit: 'percent',
    range: [0, 1],
    scale: 100,
    description: '独立评价实际交付是否遵守答案保护要求，不使用生产门禁通过率。',
  },
  {
    id: 'tool_correctness',
    label: 'Tool Correctness',
    score: 'eval.tool_correctness',
    unit: 'percent',
    range: [0, 1],
    scale: 100,
    description:
      '已声明工具调用、参数与禁用工具断言的通过比例；不代表工具结果语义正确。',
  },
  {
    id: 'safety',
    label: 'Safety',
    score: 'eval.safety',
    unit: 'percent',
    range: [0, 1],
    scale: 100,
    description: '独立审核实际交付的安全要求，不能使用生产门禁放行率。',
  },
  {
    id: 'latency',
    label: 'Latency',
    score: null,
    unit: 'seconds',
    range: [0, Infinity],
    scale: 0.001,
    description: '应用根轮次P50延迟，另展示P95；不是单个模型调用延迟。',
  },
  {
    id: 'cost',
    label: 'Cost / Task',
    score: 'eval.cost_per_task',
    unit: 'usd',
    range: [0, Infinity],
    scale: 1,
    description:
      '上报的完整任务成本均值（含备用与重试），裁判成本另列；缺计价不填0。',
  },
] as const;
export type Metric = {
  id: string;
  label: string;
  unit: MetricUnit;
  value: number | null;
  samples: number;
  description: string;
};
export type Filter = {
  column: string;
  operator: string;
  value: unknown;
  type: string;
};
export type Query = {
  view: string;
  dimensions: { field: string }[];
  metrics: { measure: string; aggregation: string }[];
  filters: Filter[];
  fromTimestamp: string;
  toTimestamp: string;
  timeDimension?: { granularity: string };
};
const filter = (column: string, value: unknown, type = 'string'): Filter => ({
  column,
  operator: '=',
  value,
  type,
});
function queries(
  filters: Filter[],
  from: string,
  to: string,
  production: boolean,
) {
  const base = { fromTimestamp: from, toTimestamp: to };
  const scoreFilters = [
    ...filters,
    {
      column: 'source',
      operator: 'any of',
      value: ['API', 'EVAL'],
      type: 'stringOptions',
    },
  ];
  const scores = (
    view: string,
    names: string[],
    dimensions = ['name'],
  ): Query => ({
    ...base,
    view,
    dimensions: dimensions.map((field) => ({ field })),
    metrics:
      view === 'scores-categorical'
        ? [{ measure: 'count', aggregation: 'count' }]
        : [
            { measure: 'value', aggregation: 'avg' },
            { measure: 'value', aggregation: 'min' },
            { measure: 'value', aggregation: 'max' },
            { measure: 'count', aggregation: 'count' },
          ],
    filters: [
      ...scoreFilters,
      {
        column: 'name',
        operator: 'any of',
        value: names,
        type: 'stringOptions',
      },
    ],
  });
  const root: Query = {
    ...base,
    view: 'observations',
    dimensions: [],
    metrics: [
      { measure: 'count', aggregation: 'count' },
      { measure: 'latency', aggregation: 'p50' },
      { measure: 'latency', aggregation: 'p95' },
    ],
    filters: [
      ...filters,
      filter('isRootObservation', true, 'boolean'),
      ...(production ? [filter('name', 'agent.turn')] : []),
    ],
  };
  return {
    root,
    numeric: scores('scores-numeric', [
      'eval.overall',
      'eval.teaching_correctness',
      'eval.guidance_logic',
      'eval.latency_ms',
      'eval.cost_per_task',
      'eval.grading_cost',
    ]),
    boolean: scores('scores-boolean', [
      'eval.task_success',
      'eval.tool_correctness',
      'eval.safety',
      'eval.answer_protection',
    ]),
    status: scores('scores-categorical', ['eval.status'], ['stringValue']),
    trend: { ...root, timeDimension: { granularity: 'day' } },
  };
}
export function productionQueries(
  environment: string,
  from: string,
  to: string,
) {
  return queries(
    [filter('environment', environment), filter('experimentId', '')],
    from,
    to,
    true,
  );
}
export function experimentQueries(id: string, from: string, to: string) {
  return queries([filter('experimentId', id)], from, to, false);
}
function number(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}
export function periodSummary(data: {
  taskCount?: number;
  offline?: boolean;
  root: Row[];
  numeric: Row[];
  boolean: Row[];
  status: Row[];
  trend?: Row[];
}) {
  const root = data.root[0] || {},
    taskCount = data.taskCount ?? number(root.count_count) ?? 0,
    scores = [...data.numeric, ...data.boolean];
  const metrics: Metric[] = metricPolicy.map((p) => {
    if (p.id === 'latency' && data.offline) {
      const row = data.numeric.find((s) => s.name === 'eval.latency_ms');
      const valid =
        row &&
        row.count_count > 0 &&
        number(row.avg_value) !== null &&
        row.min_value >= 0;
      return {
        id: p.id,
        label: 'Execution Latency (avg)',
        unit: p.unit,
        value: valid ? row.avg_value / 1000 : null,
        samples: row?.count_count ?? 0,
        description: '实际执行耗时均值；排除云端评分等待。',
      };
    }
    if (p.id === 'latency')
      return {
        id: p.id,
        label: p.label,
        unit: p.unit,
        value:
          root.count_count > 0 && number(root.p50_latency) !== null
            ? root.p50_latency / 1000
            : null,
        samples: number(root.count_count) ?? 0,
        description: p.description,
      };
    const row = scores.find((s) => s.name === p.score),
      count = number(row?.count_count) ?? 0,
      avg = number(row?.avg_value),
      min = number(row?.min_value),
      max = number(row?.max_value);
    const valid =
      count > 0 &&
      avg !== null &&
      min !== null &&
      max !== null &&
      min >= p.range[0] &&
      max <= p.range[1];
    return {
      id: p.id,
      label: p.label,
      unit: p.unit,
      value: valid ? avg! * p.scale : null,
      samples: count,
      description: p.description,
    };
  });
  const status: Record<string, number | null> = {
    pass: null,
    fail: null,
    error: null,
    not_run: null,
  };
  for (const r of data.status)
    if (Object.hasOwn(status, r.stringValue) && number(r.count_count) !== null)
      status[r.stringValue] = r.count_count;
  const grading = data.numeric.find((s) => s.name === 'eval.grading_cost');
  return {
    taskCount,
    metrics,
    status,
    p95Seconds:
      !data.offline && root.count_count > 0 && number(root.p95_latency) !== null
        ? root.p95_latency / 1000
        : null,
    gradingCost:
      grading && grading.count_count > 0 ? number(grading.avg_value) : null,
    trend: data.trend || [],
  };
}
export function metricDelta(
  current: number | null,
  baseline: number | null,
  unit: MetricUnit,
): number | null {
  if (current === null || baseline === null) return null;
  return unit === 'points' || unit === 'percent'
    ? current - baseline
    : baseline === 0
      ? null
      : ((current - baseline) / baseline) * 100;
}
export function experimentIdentity(metadata: Row | null | undefined) {
  const m = metadata || {},
    d = m.config_digest ?? m.config_snapshot?.digest;
  return {
    configDigest: typeof d === 'string' && /^[0-9a-f]{64}$/.test(d) ? d : null,
    codeVersion: m.git_sha ?? m.git_commit ?? m.code_version ?? null,
    datasetVersion: m.dataset_version ?? m.dataset_hash ?? null,
    graderVersion: m.grader_version ?? null,
    rubricVersion: m.rubric_digest ?? m.rubric_version ?? null,
  };
}
