---
slug: ward-turn-homework-policy
created: 2026-11-28T05:39:28Z
status: in-progress
---

# Ward 每轮作业保护

目标契约见[Agent 路由设计](../../docs/technical/design-agent.md)与[答疑设计](../../docs/technical/domain-tutoring.md)。

## 验收标准

- [x] 新对话、无 Sprint 的首轮作业请求进入启发答疑。
- [x] 同一对话先问方法，再直接索要结果，随后要求发音。每次依据当轮输入与必要历史决策，索答守住文字和配图出口，发音正确交付。
- [x] 既有场景、路由提示和入口快捷动作不能跳过对新自然语言请求的判断；纯协议确认动作维持既有幂等行为。
- [x] 意图缺失或无效时澄清或走保护路径；未完成判定前不发送候选内容，不额外串联第二次意图分类。接口拒答时不写教学事实。
- [x] 比对同一批 Langfuse 题与评分口径，另从对话入口验三轮切换；Android 调试包实机结果能对应后端 trace。

## 实现计划

1. 在现有 Companion 入口补协议测试与三轮行为测试，让路由提示短路分类和图片不明确时默认进入 Planning 的旧行为先暴露。
2. 扩展 IntentProposal、ModelIntentClassifier 及 Admin 测试配置契约。把当轮请求和教学策略放进同一次意图调用，核验测试实例加载回执。
3. 在 CompanionCoordinator 和 IntentRouter 消费结构化决定，接现有 Tutoring 教学出口与发音能力，检查工具调用和流式输出顺序。
4. 跑 pytest、Langfuse 对照和 Android 调试包连续对话。在执行结果中区分路由、教学质量、供应商失败。确认后进入 Gate 2。

## 实现清单

- [x] 开工前已跑 Companion 路由与 Tutoring 延迟优化两组现有测试，43 passed。
- [x] ADB 已识别真机 2211133C，已安装 com.duxue.app.debug。
- [x] 冻结评测输入、裁判和配置基线
- [x] 实现与自动化回归
- [x] 真实评测与 Android App 真机联调
- [ ] Gate 2 人工确认

## 联调记录

- Admin 测试工作草稿 46cdcc97-bd1c-4008-a715-c25feee873b9 从 revision 6 升级至 8，运行实例回读摘要 6eef0bcd2454d09a414dd6e3044208274389a49e141a159ef9a9ff9d157c0980。生产发布未操作。旧配置可继续加载。
- 相同 Dataset 时刻与裁判下，Langfuse 的 pedagogy-remainder-next-step 在改动前后各一次通过。结果位于服务端 var/evals/ward-turn-policy-before-20261128 和 ward-turn-policy-final-20261128。
- 真实入口三轮强制携带冲突的 planning 提示，三角形内角题首轮提示、续轮索答、改问发音对应 trace 947b6f531ebd11767eb304b9d9b72dcd、4a201496790811d1f2601626a3018da6、453e8fe94dd6949db273ba715f5a8bee；语义决策依次为 homework、homework、pronunciation。另用独立测试 Ward 上传方程题图，首轮仅提示移项思路。
- Android 2211133C 通过 USB reverse 从设备自身发起绑定与三轮 HTTP 对话，Run e625589c-6ead-4464-a92d-ff2343dc6804。随后在已登录 Ward 的现有调试版完成 App 内验收，见下。
- 服务端全量 pytest 1605 passed、4 skipped；新增拒答覆盖后，相关套件复验 215 passed。一次性 PostgreSQL 使用本机 postgresql@14 的服务端工具链。

- Android 2211133C 上从 Ward 首页进入原生对话，以模拟语音通过麦克风输入。长 9 宽 5 的周长题先收到思路提示，直接追问时保留最终数值；续问 apple 的发音后页面出现音标、重音说明、三档语速及播放按钮。三条有效输入的 trace 分别为 4cf8622e1e819f32d56fb48769a5dfe5（homework）、f855e783cfcb6f96ca009b242101be14（homework）、173bf4bb531e3f39ed4922262a25a5c9（pronunciation）。期间一次 ASR 误转写，重说后识别正确；误转写轮未计入这三条。索答轮未泄露最终数值，但提示一次给了多个计算动作。
