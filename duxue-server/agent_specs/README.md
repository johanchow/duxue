# Agent 运行配置入口

## 配置维护与验收

修改前阅读 [Agent 设计中的配置铁律](../../docs/technical/design-agent.md#配置铁律)。管理台提供[草稿升级与版本导出命令](../../duxue-admin/README.md#配置快照导入导出)，后端读取方式见下文「本地联调」。

## 代码保留的内容

- `contracts.json`：稳定ID、输入输出契约、Prompt变量声明、处理器与工具授权上限，不含Prompt正文、模型名称/生成参数或静态工具正文。
- Workflow处理器/条件注册、必经门禁及执行次数安全上限留在Python中；不保留完整Workflow JSON副本。流程拓扑只存在Admin发布包及其导出/缓存中，已升级的答疑主图支持受控路径与新 Run 灰度编辑，见[答疑主图的执行与切换](../../docs/technical/domain-tutoring.md#13-答疑主图的执行与切换)。
- `schemas/`：统一执行结果协议。

代码契约、处理器注册与发布包自带的Workflow共同形成兼容性摘要；计算时不读取本地流程基线，新增代码契约需要显式升级旧包。发布包必须完整包含代码契约及注册workflow要求的逻辑文件。代码不生成可编辑默认值。发布编译阶段同时构建并验证组件与流程目录；运行、管理目录、调试和评测均读取所选完整包，每轮固定、发布/回滚后下一轮切换。不能扩权或跳过必经审核。

## 运行模式

| 参数 | 含义 |
|---|---|
| `AGENT_CONFIG_SOURCE=admin` | 业务 API/Worker 唯一支持的配置来源，默认渠道为 release |
| `AGENT_CONFIG_CHANNEL` | `release` 跟随环境发布；本机显式设为 `working-draft` 跟随测试 Admin 工作草稿，没有草稿时读取测试发布。草稿渠道不写恢复缓存 |
| `AGENT_CONFIG_SOURCE_URL` | 私有发布接口前缀，例如`http://duxue-admin:3000/api/internal` |
| `AGENT_ADMIN_INTERNAL_TOKEN` | 与Admin一致、至少32字符的内部密钥 |
| `AGENT_CONFIG_CACHE` | 最后成功发布的持久缓存路径，正式Docker挂载`/app/var/admin` |
| `AGENT_CONFIG_SOURCE=snapshot` | 离线诊断或评测固定使用显式导出的配置，不轮询Admin |
| `AGENT_CONFIG_SNAPSHOT` | 完整导出文件路径，默认Server下`var/admin/release.json`，Git忽略 |

离线快照必须含`id/digest/bundle`，并验证完整性、代码契约和摘要；缺失/错误时明确拒绝，不从仓库补值。生产验证环境为prod，缓存与在线来源都不能混入测试环境或草稿。Admin暂时不可用时继续使用已验证缓存；无缓存时AI调用返回配置未就绪。每轮应用调用固定一次快照，发布/回滚只影响后续调用。API与Celery子进程分别维护加载状态。

`AI_MODEL_OVERRIDES`已停用；模型变化在Admin维护。评测的`--model/--variant`只修改评测进程内的实验对象，不回写快照或Admin。

## 本地联调

本地 App 联调在 Server 的 `.env` 使用 `AGENT_CONFIG_SOURCE=admin`、`AGENT_CONFIG_CHANNEL=working-draft`、`AGENT_CONFIG_SOURCE_URL=http://127.0.0.1:3021/api/internal`，内部通信密钥与本机测试 Admin 一致。约每 30 秒检查数据库草稿 revision，每轮答疑固定使用一版。用内部鉴权访问本机 API 的 `GET /internal/agent-admin/catalog` 查看实际 draft_id、revision、digest 和工具绑定。验证已发布行为时将渠道设为 `release`。

## 离线评测

离线评测按[Admin快照导入导出说明](../../duxue-admin/README.md#配置快照导入导出)固定一份导出，用命令参数传递给评测进程。

```bash
cd duxue-server
.venv/bin/python -m evals validate
.venv/bin/python -m evals run --component companion.intent --samples 1 \
  --config-snapshot var/admin/release.json
```

四种真实评测命令都支持`--config-snapshot`；入口在导入模型前固定来源，同一进程所有线程使用同一包，结果记录发布/草稿身份和完整digest。`validate/export/compare`数据集操作不要求Agent配置或在线Admin；评测数据、标注继续由Git维护。

## 单测与部署验证

`tests/fixtures/`是明确隔离的历史回归输入，由`tests/conftest.py`显式安装；不随镜像发布，不是业务配置维护源。部署前执行`python -m app.agent_specs preflight`验证Admin发布或兼容缓存，失败保留原容器。初次生产接入步骤见[部署文档](../../docs/deployment.md#生产server接入admin配置)。

统一离线 runner 不再使用配置包中的旧 `evals.semantic-judge`，独立评分由 Langfuse 原生 Evaluator 承担；执行、快照与限制见[离线评测设计](../../docs/technical/eval-offline.md)。
