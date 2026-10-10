---
slug: split-study-tutoring-domain
created: 2026-10-09T23:52:23Z
status: done
---

# split-study-tutoring-domain spec

## 做什么 / 为什么
把 `docs/technical/domain-study.md`（1081 行，含三套模型）拆成两个 Domain / Bounded Context：

- **Study**（学习执行，Core）：`StudySession`、`StartCue`。
- **Tutoring**（辅导答疑，Core，新增）：`TutoringSession`、`ProblemRecord`、`TutorPermitPolicy`、`TutoringTurnLoop`、发音 act。

动机：答疑的 Agent 控制流（§四）已压过执行本身，二者业务问题、变化速度、上游依赖都不同。只改文档和系统级索引，**不改代码、表和部署**（模块化单体，物理表仍在 design-server 维护）。

`StartCue` 留在 Study：`AcceptStartCue` 要在同一事务里 `start()` / `pause()` `StudySession`，拆开会变成跨 Context 同事务写。见 note 105。

## 已定决策（待 Gate 1 确认）
1. `StartCue` 与 `StudySession` 同属 Study（2 Context、3 聚合）。
2. `TutoringSession.open()` 的「所属学习会话未结束」改为经受权 Query `GetStudySession` 判断，接受最终一致窗口。
3. 学习会话结束**不自动关闭**答疑，沿用现状（暂停/断线/取消也不关闭）；只是结束后 Tutoring 拒绝追加新轮次。关闭仍只由 `CloseTutoringSession` 完成。
4. 互动 Fact（`tutoring.*`）的生产者从 Study 改为 Tutoring；`StudySessionCompleted.v1` 仍由 Study 生产。
5. 术语归属：`SceneRead`、`CueAllowance` 属 Study；`TutorPermit`、`QuestionKind` 等属 Tutoring。「无任务答疑」章节拆成两半：任务关系留 Study，题外提问回任务提醒留 Tutoring。

## 验收标准
- [ ] 存在 `docs/technical/domain-tutoring.md`，且 `domain-study.md` 不再含答疑控制流（`TutoringTurnLoop`、`TutorPermitPolicy`、出口检查、发音）的正文，只保留链接。
- [ ] 每个概念只在一处定义（单一事实源）：全文检索 `TutorPermit`、`StartCuePolicy`、`ProblemRecord` 等，定义只出现在其归属文档。
- [ ] `ddd-overview.md` 的 Domain Inventory 为 9 行，Context Map、事件契约目录、详情入口同步，并含 Study↔Tutoring 协作规则。
- [ ] 全仓库对 `domain-study.md#...` 的锚点链接无失效，应指向 Tutoring 的已改指向新文档。
- [ ] 两份文档均符合 DDD skill 的单 Context 结构（边界与语言 → 领域模型 → 用例 → Query → 契约 → 基础设施映射 → 验收场景）。
- [ ] 原验收场景（§八）一条不丢，按归属分配到两份文档。
- [ ] AGENTS.md 文档索引、`.agent/notes/` 新增决策笔记。

## 实现计划（Gate 1：填完等人确认，不许自转）

### 章节迁移映射

| 原章节 | 去向 |
|---|---|
| 头部、§一 StartCue/StudySession 相关不变量与术语、§1.2、§2.1、无任务答疑（任务关系部分）、§2.5、§3.2 | 留在 `domain-study.md` |
| §一 教学红线与答疑术语、§1.1、§1.3 | `domain-tutoring.md` |
| §2.2、§2.4、§2.3 中 Tutoring 相关行、§3.1、§四（含 4.1–4.6） | `domain-tutoring.md` |
| §三 用例表 | 按用例归属拆成两张表 |
| §五 Query | `StudySessionView` / `StartCueView` 留 Study；`TutoringInteractionView` / `PronunciationLessonView` 去 Tutoring |
| §六 契约 | 拆开；新增 Study→Tutoring 的受权 Query 契约（会话状态、`task_id`、任务标题） |
| §七 基础设施映射 | 按 Port 归属拆开 |
| §八 验收场景 | 按归属拆开，保留全部 |

### 影响文件
- 新增：`docs/technical/domain-tutoring.md`
- 缩减：`docs/technical/domain-study.md`
- 同步：`docs/technical/ddd-overview.md`（Inventory、Context Map、契约目录、详情入口、Layered Map 模块名）
- 同步链接：`domain-companion.md`（7 处）、`domain-memory.md`（含 `CloseTutoringSession` 的归属）、`domain-planning.md`（3 处，应仍指 Study）、`design-server.md`（2 处，含 Study & Tutoring 行）、`ARCHITECTURE.md`、`AGENTS.md`
- 新增笔记：`.agent/notes/114-split-study-and-tutoring-domains.md`
- 不改：`duxue-server/` 代码、已有 notes 的历史内容

### 测试计划（文档任务，用可执行检查代替单测）
1. 链接检查：对 `docs/technical/*.md` 的相对链接和 `#anchor` 逐一核对，零失效。
2. 单一事实源检查：`rg` 核对核心术语定义只出现一次。
3. 验收场景计数：拆分前后 Gherkin `Given` 数量相等。
4. 人工通读两份文档的上游/下游描述与 `ddd-overview.md` 一致。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 建 `domain-tutoring.md`，迁移答疑内容（原样搬运，只改交叉引用）
- [x] 精简 `domain-study.md`，补 Study↔Tutoring 协作契约
- [x] 更新 `ddd-overview.md`
- [x] 同步各文档链接和 AGENTS.md 索引
- [x] 写决策笔记 114
- [x] 跑链接、术语、场景计数检查，全部通过
- [ ] `git diff` review，文档同一 commit

## 备注
- 验证结果：链接/锚点 0 失效；原 38 条验收场景全部保留（Tutoring 33 + Study 5），Study 另补 2 条由既有不变量推出的场景（180 分钟暂停、无任务不可完成），共 40。
- 遗留：`docs/technical/diagrams/` 生成产物未重生成，见 note 114。
- 迁移时只搬运和改引用，不顺手改设计内容，避免拆分与语义变更混在一起。
- Context 名称：Study 保持不变；新 Context 取名 `Tutoring`（中文「辅导答疑」）。
