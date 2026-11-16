# Omni-Edu 托管评测运行记录（2026-11-16）

当前 Langfuse 五个 Dataset 共248条 ACTIVE 用例：Omni-Edu 新增209条，既有39条。其中应用任务233条、裁判校准15条。当前记录不能代替人工教学质量验收。

| Dataset | 用例数 |
|---|---:|
| judge-calibration | 15 |
| orchestration-tools | 5 |
| answer-protection-safety | 6 |
| guidance-logic | 104 |
| teaching-correctness | 118 |

## 已完成批次

首轮全量使用本地冻结代码执行、Langfuse原生裁判评分，248条全部完成：**205 pass /43 fail /0 error**，原生裁判版本在运行期间未变化。证据目录：`duxue-server/var/evals/langfuse-all-248-20261116-151655/`。

随后固定此前进度中最先完成的20条失败用例（截至`omni-chinese-010`），独立复测得到 **13 pass /7 fail /0 error**。这不是全43条失败复测，也不是全量通过率。业务门禁和两个裁判提示词同时调整：`eval.teaching_correctness`、`eval.guidance_logic`由v4升级v5，其余评分器不变，原分数未覆盖。因此不能将13条恢复全部归因于业务能力提升。证据目录：`duxue-server/var/evals/langfuse-fail20-recheck-20261116-170204/`。

该20条中的化学007虽获原始pass，但视觉评分证据仍不完整；其余19条纯文本为12 pass /7 fail。7条失败的复核见同目录`failure-review.json`：输出协议1条、明确内容精度问题3条、缺少学生进展依据的多轮回复2条，以及1条裁判只返回分数、原因尚未确认的用例。助手复核意见不覆盖原始评分。

## 最新全量重跑：尚未完成

使用`a14b791`及当时未提交的托管适配，冻结721份源码、四路并发、每条任务执行一次。配置摘要为`cc5614773aae3498361cf6caaedaefec4cd79fc77dd2c10550285437d3c44a62`，Dataset版本固定为`2026-11-16T12:10:20.081165+00:00`；教学正确性和引导逻辑裁判均使用v5。

运行在21:43因DashScope HTTP400 `Arrearage`中断，已落盘237条：**220 pass /16 fail /1 error**，另11条未完成。其中236条有效结果为220 pass /16 fail；语文009属于接口错误，不能当作题目能力失败。不能用220/237宣称全量通过率。

用户确认充值后，核验冻结源码未变，但5个LLM裁判仍被Langfuse自动暂停，原评分版本均未变化。恢复前需要重新激活裁判，随后按原代码、配置、Dataset和评分版本统一补跑1条接口错误及11条未完成任务，保留236条有效结果和16条质量失败，不重刷质量失败取高分。

本机证据目录：`duxue-server/var/evals/langfuse-all-248-rerun-20261116-201049/`；中断详情、完整恢复集合和当前状态分别在`INTERRUPTION.md`、`interruption.json`、`recovery-state.json`。这些运行产物保留在Git忽略目录，凭据、模型请求正文及临时图片签名URL不纳入提交。完整结果须以恢复后合并及校验通过的报告为准。

## 评分证据限制

Omni-Edu的17张图片保持OSS存储。导师模型获得了实际图像输入，但核验化学007的云端原生裁判请求发现，当前URL仅嵌入序列化文本，没有形成图像内容块。相关原始分数保留，图文用例必须单列`needs_image_evidence`，不能作为已完成视觉评分验收的证据。对应核查记录为首轮目录`visual-grading-gap.json`。

英语010原题面含答案解析，继续以`review_required=true`标记，未静默改题或改历史分数。原生媒体校准图片与Omni-Edu OSS图片分别统计。以上自动评分均未完成教师校准，也不能据此保障九科高考问题的稳定解答和引导。

托管协议、运行方式及图片引用说明统一见[离线评测设计](eval-offline.md#omni-edu-托管迁移2026-11-16)。
