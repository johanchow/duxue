# Loop: feature-spec（单文件 + 2 卡点）

> 目标：让 agent 自主迭代到收敛，人只在两个 Gate 介入。
> 定位：一个 feature = **一个 spec 文件**（验收 + 计划 + 完成度清单）。
> 这也是 `.claude/skills/feature-spec` skill 所执行的流程（skill 为可执行真身，本文件为设计 / 参考）。

## 步骤

1. **起 spec**：`bash .agent/scripts/new-spec.sh <slug>` → 生成 `.agent/specs/<slug>.md`（含 front-matter + 模板）。
2. **填验收 + 计划**：在 spec 里写「验收标准」与「实现计划（影响文件 + 测试计划）」。
   → **Gate 1（计划确认）**：填完即停，等用户确认再动手。审计划比审代码便宜 10 倍。
3. **小步实现（自主循环）**：
   - 把计划拆小步，每步改 + 配测试；红了回到上一步修，全绿才算这步完。
   - 每完成一项，把对应 `- [ ]` 改成 `- [x]`（**完成度即进度**）。
   - 工具链以本仓库为准（`.nvmrc` / `pnpm` / `npm`），不绕过。
4. **收敛 + 验收**：验收标准全绿 **且** 清单全 `[x]` → **Gate 2（验收）**，等用户确认。
5. **归档（收工）**：spec 顶部 `status: draft` → `done`；`bash .agent/scripts/archive-spec.sh <slug>`；`git diff` review 后文档与代码同一 commit。

## 硬约束

- 测试全绿是退出硬门槛，不许自评「做完了」。
- 不归档 = 未收工（spec 不得遗留在 `.agent/specs/`）。
- 单一事实源：spec 文件是唯一真相，别处只链接。
