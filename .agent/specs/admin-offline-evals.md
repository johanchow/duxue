---
slug: admin-offline-evals
created: 2026-11-11T01:06:59Z
status: in_progress
---

# Admin Evaluation / Langfuse集成

## 范围与授权
用户确认：Admin仅做Overview、Experiments摘要与Production聚合；Datasets/Evaluators/Human Review直接外链Langfuse，不用iframe。明确要求撤回此前自建评测代码和表结构。此确认替代旧计划Gate 1，继续实施。

## 验收标准
- [x] 备份测试Admin旧运行/复核/产物后删除eval_runs、eval_reviews及010迁移状态；撤回相关代码、OSS依赖和旧功能文档，不改既有runner/grading或无关工作区。
- [x] Admin服务端用独立环境配置读取Langfuse API；凭证不进浏览器，鉴权、项目绑定、超时/错误、缓存隔离均有测试。
- [x] Overview显示真实指标及基线差值、评分数量/任务数与缺失状态；离线按实验比较，Production按明确环境和等长时间窗比较，不把门禁通过率当质量/安全。
- [x] Experiments读Langfuse列表、游标翻页；以明确配置摘要关联已有Admin草稿/发布，无第二套结果表。
- [x] Datasets 内维护 Test Cases，无独立一级入口；三个外链可用且标识新标签页/独立权限；没有iframe、自建用例/复核CRUD或报告上传。
- [x] 完整Admin测试、类型、构建及真实Langfuse只读联调、浏览器验证通过；文档/笔记更新，未部署生产。

## 实现计划
1. 备份并撤回旧数据结构、实现和依赖；保留只读备份与撤回记录。
2. 按官方v4 Public API实现客户端、指标协议及读取端点；使用现有凭证一次性配置Admin独立.env，运行时不读取Server.env。
3. 实现三个原生页面与三个外链，必要业务关联利用现有Admin表，无新增结果存储。
4. 验证真实读接口/边界、未知值与采样差异，更新唯一技术设计和使用说明。

## 非本轮范围
不迁移生产配置来源，不执行远端删除或将本地旧报告伪装为新实验，不新建自动发布门槛。既有Langfuse尚无Experiment；空状态与未上报指标必须如实展示。

## 验证与待验收
实现与自动检查完成，用户已授权提交当前实现；后续链路仍未完成，暂不归档、不部署。Admin 36项测试、类型检查、生产构建通过；真实 Langfuse 三页面浏览器只读验收通过，桌面/手机截图位于 `.local/evaluation-*.png`。回撤后的测试库确认两表及010记录均不存在。基线历史不可访问的降级、角色权限、摘要关联及旧接口消失均有回归测试。

局限：现有项目无实验、无 canonical eval.*，本地报告尚未同步至 Langfuse；Overview 仅选当前窗口第一页50个实验，完整列表可翻页或进入 Langfuse。尚未执行远端创建/删除、生产发布或历史报告补传。

## 用户追加：Langfuse资源初始化
用户已确认创建5 Dataset、6核心Evaluator、13正式评分定义、2人工队列；本轮创建5/6/13/1。原2个监测Evaluator、6个监测Score保留；旧answer_quality归档。19项新增CODE本地测试通过、远端定义回读验证完成。第2队列受Hobby限制，LLM模型连接为空，均已发起用户问题；未绑定生产自动规则。资源初始化不包括历史报告/样本导入、评分链路替换或Admin新指标适配。

用户后续确认共用1个人工队列，数量要求更新为1；该项不再受套餐阻塞。共享策略已登记，既有队列ID不变；模型连接仍待确认，自动入队仍属后续接通工作。

模型连接追加已完成：用户授权复用Server供应商服务，5个LLM Judge绑定duxue-dashscope/qwen3.8-flash并通过合成文本连通性测试；模型连接阻碍解除。图片评分、真实样本校准、runner接通与Admin指标适配仍未完成。

## 本次提交验证
2026-11-11：Admin 36 tests passed、typecheck/build 通过，Langfuse CODE evaluator 19 tests passed。用户明确授权提交 Admin 菜单、Langfuse 集成及资源定义；不包含平台 SSH 排查笔记、图片/PDF、IDE 配置。
