---
slug: eval-grading-v2
created: 2026-11-10T16:35:21Z
status: draft
---

# 离线评测判分协议 v2

## 做什么 / 为什么
按用户已确认的[评测设计§五](../../docs/technical/eval-offline.md#五判分原则与协议)，改造全部现有离线评测：数据、执行器、独立语义评分、报告及CLI。保留40份文件/77检查点的原始证据与回放方式，不扩充用例覆盖，不提升proposed标签。

## 验收标准
- [x] 四类用例统一使用dialogue-eval.v2/checks[].grading；全部检查点具备确定性断言，教学回复具备逐例语义标准，旧语义字面匹配不再判分。
- [x] 严格验证字段/运算/类型、工具断言、评分阈值、rubric引用与唯一ID；缺观测数据不伪装为空轨迹或通过。
- [x] 评分仅读取实际交付结果及截至本轮的上下文/原图；期望不进入被测模型，生产Judge不替代评分Judge。
- [x] 单步、合成多轮、真实回放及固定判官共享逐项结果与all_required规则；错误、未执行、缺图、多轮中止和image-context排除项均可追溯。
- [x] 工具调用记录真实工具名/参数/结果；字段与参数检查使用确定性协议，不扫描正文判语义；效率先记录，不新增预算门槛。
- [x] 报告保留分数/证据/裁判配置及版本、人工复核和校准状态；命令退出码、比较和导出适配新协议，未校准结论仅供实验，不启用正式质量门槛。
- [x] 显式迁移幂等，消息、图片、候选、来源、上下文、分支及标签不变；新增rubric逐例整理，不机械翻译答案关键词。
- [ ] 定向/全量测试、数据校验、配置契约检查及diff review通过；环境错误与真实模型验收分别报告。

## 实现计划
1. 新增统一grading/结果类型与严格校验，适配dialogue/schema及内部投影；先补非法协议及状态聚合测试。
2. 改造graders/outcome/runner及工具记录，增加独立语义评分适配器；使用独立Admin组件，不绕过组件网关。
3. 统一episode/conversation/judge执行器、report与CLI，覆盖实际正文/多模态输入、未来信息隔离、失败中止、未执行分母和裁判故障。
4. 逐例阅读现有数据和note，保留确定性期望，将开放语义要求整理为rubric；适配migrate/export/dataset及哈希，验证原始证据不变。
5. 更新唯一设计文档和笔记，运行tests/unit/evals、模型调用约束及相关组件测试，再运行服务端全量；如接入Admin，追加其契约/快照兼容测试。

主要影响：`duxue-server/evals/`、`duxue-server/tests/unit/evals/`及相关AI契约测试、`docs/technical/eval-offline.md`。新裁判若归Admin管理，还需修改组件契约、快照升级与对应管理端支持，不能仅修改evals目录。

用户已接受整体改造、独立Admin裁判接入及未校准实验评分策略；Gate 1已确认。代码与数据迁移已实现，当前待解决全量测试环境阻塞，再进行Gate 2验收。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 核对当前协议、四类执行器、配置约束及迁移范围
- [x] 明确新裁判配置与校准阶段的结果用途
- [x] 统一schema、确定性grader和结果协议
- [x] 接入独立语义grader及真实工具轨迹
- [x] 改造四类执行器、CLI、导出和报告
- [x] 逐例迁移全部现有数据与rubric
- [ ] 测试、文档、review及人工验收

## 验证与待办

- 40份文件/77检查点通过validate；50个教学检查点均有公共评分与逐例二元要求。显式迁移幂等（0待迁移）。
- 已逐文件对比Git原版：除版本与grading外，消息、来源、图片、原候选、输入快照、分支和复核标签完全一致。
- 已覆盖严格类型/工具调用参数、缺失轨迹、独立裁判异常、原图输入、交付正文/被拒草稿隔离、配置升级保留与幂等、多轮not_run、报告分母等回归。
- 独立裁判固定于Admin完整快照；本轮仅代码契约、显式升级脚本与测试夹具改造，未发布Admin、未调用真实模型。旧包部署前必须显式升级，步骤见设计文档。
- 最终全量pytest：987 passed、1 skipped、6 errors（另3个subtests通过）；无断言失败。Ruff F/E9、git diff --check通过。全量测试仍受本机PostgreSQL初始化阻塞：`initdb: could not look up effective user ID 501: user does not exist`。6项数据库集成测试尚未进入测试主体，不以跳过替代通过。
- 待补：修复环境或使用隔离测试库后重跑全量；真实模型抽样及人工校准另行验收。测试与验收未全绿前不归档、不宣称收工。

已有无关platform笔记、.vscode及参考PDF未改动，不纳入本次改造。

- 失败诊断修复（2026-11-11）：用户授权明确问题直接修复、不确定项留报告。新增3项评分上下文/生成器隔离/显式刷新配置测试先红后绿，相关315项通过；grader v2.2与候选选图Prompt验证见`duxue-server/var/evals/grading-v2-fixes-20261111/REPORT.md`。冻结原回复证明3项评分上下文误判修正；全量候选63 pass/11 fail/3 not_run，未全部通过且不改标。剩余数学、句子引用、任务切换、生产判官与裁判格式波动留待处理。PG按用户要求暂缓；其余测试989 passed/1 failed/1 skipped，数学执行器macOS环境键断言失败，不能勾选全绿验收。未发布Admin。

- 用户指向Server `.env`后已只读验证：DATABASE_URL指向RDS的duxue-test，连接与SELECT 1均成功；当前角色无CREATEDB/SUPERUSER权限，未配置TEST_GATEWAY_DATABASE_URL。现有6项集成测试需可清空的duxue_gateway_test_*库，并会执行迁移/降级，不能直接在共享业务测试库运行。未修改数据库。

- 用户明确本轮先不处理6项PG集成环境问题；不再以选择测试库作为继续讨论的前提。已澄清987项是自动化测试，尚未按v2调用真实模型跑全部用例。为查看协议，用实际执行器与测试替身生成ignored `var/evals/grading-v2-format-example.json`，标记example_only/simulated，含pass/fail/error/not_run四种结果，不作为模型质量结论。

- 用户随后授权执行全部真实离线评测：使用.env所指本机Admin R9导出，完成数学契约兼容迁移（不启用math，不改原模型/Prompt/工具授权）及独立裁判升级，未发布。40份/77检查点各采样1次，结果51 pass、15 fail、1 error、10 not_run（多轮前序失败/异常中止）；5段episode中2段完整通过。报告见ignored `duxue-server/var/evals/grading-v2-live-20261111-072341/README.md`，五组原始JSON、失败明细、配置副本、代码摘要及命令/日志均保留。结果不全通过；读音卡视为隐藏字段、旧题保护被质量裁判判为应直答等疑似评分问题另标待校准，不改原分数、不重抽到通过。当前待办是问题复核/人工校准；PG集成按用户要求暂不处理。
