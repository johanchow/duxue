'use client';

type Rule = {
  id: string;
  assessment_rule: string;
  min_continuous_seconds: number;
};
type Group = 'offer_help' | 'invite_return';
export type ObservationPolicy = {
  schema_version: 1;
  groups: Record<Group, Rule[]>;
};

export function ObservationRules({
  policy,
  change,
}: {
  policy: ObservationPolicy;
  change?: (policy: ObservationPolicy) => void;
}) {
  function update(group: Group, rows: Rule[]) {
    change?.({ ...policy, groups: { ...policy.groups, [group]: rows } });
  }
  return (
    <section>
      <h2>摄像头提醒规则</h2>
      {(['offer_help', 'invite_return'] as const).map((group) => {
        const rows = policy.groups[group];
        return (
          <fieldset key={group}>
            <legend>
              {group === 'offer_help' ? '提供帮助' : '邀请回到学习'}
            </legend>
            {rows.map((rule, i) => {
              function replace(fields: Partial<Rule>) {
                update(
                  group,
                  rows.map((row, index) =>
                    index === i ? { ...row, ...fields } : row,
                  ),
                );
              }
              return (
                <div key={rule.id}>
                  <label>
                    可见行为描述
                    <textarea
                      readOnly={!change}
                      maxLength={500}
                      value={rule.assessment_rule}
                      onChange={(e) =>
                        replace({ assessment_rule: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    连续秒数
                    <input
                      readOnly={!change}
                      type="number"
                      min={15}
                      max={3600}
                      value={rule.min_continuous_seconds}
                      onChange={(e) =>
                        replace({
                          min_continuous_seconds: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  {change && i > 0 && (
                    <button
                      onClick={() => {
                        const reordered = [...rows];
                        [reordered[i - 1], reordered[i]] = [
                          reordered[i],
                          reordered[i - 1],
                        ];
                        update(group, reordered);
                      }}
                    >
                      上移
                    </button>
                  )}
                  {change && (
                    <button
                      onClick={() =>
                        update(
                          group,
                          rows.filter((row) => row.id !== rule.id),
                        )
                      }
                    >
                      移除规则
                    </button>
                  )}
                </div>
              );
            })}
            {change && rows.length < 8 && (
              <button
                onClick={() =>
                  update(group, [
                    ...rows,
                    {
                      id: crypto.randomUUID(),
                      assessment_rule: '',
                      min_continuous_seconds: 120,
                    },
                  ])
                }
              >
                添加规则
              </button>
            )}
          </fieldset>
        );
      })}
      <p>
        达到时长后再评估是否值得询问。休息期间暂停提示，两类邀请共享每日两次额度，间隔至少二十分钟。
      </p>
    </section>
  );
}
