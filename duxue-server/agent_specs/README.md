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
| `AGENT_CONFIG_SOURCE=snapshot` | 仅用于单元测试或纯离线无网复现；日常本地联调与本地离线评测一律直连 Admin |
| `AGENT_CONFIG_SNAPSHOT` | 仅在 `snapshot` 模式下使用的本地快照路径，Git 忽略 |

离线快照必须含`id/digest/bundle`，并验证完整性、代码契约和摘要；缺失/错误时明确拒绝，不从仓库补值。生产验证环境为prod，缓存与在线来源都不能混入测试环境或草稿。Admin暂时不可用时继续使用已验证缓存；无缓存时AI调用返回配置未就绪。每轮应用调用固定一次快照，发布/回滚只影响后续调用。API与Celery子进程分别维护加载状态。

`AI_MODEL_OVERRIDES`已停用；模型变化在Admin维护。评测的`--model/--variant`只修改评测进程内的实验对象，不回写快照或Admin。

## 本地联调

本地 App 联调在 Server 的 `.env` 使用 `AGENT_CONFIG_SOURCE=admin`、`AGENT_CONFIG_CHANNEL=working-draft`、`AGENT_CONFIG_SOURCE_URL=http://127.0.0.1:3021/api/internal`，内部通信密钥与本机测试 Admin 一致。约每 30 秒检查数据库草稿 revision，每轮答疑固定使用一版。用内部鉴权访问本机 API 的 `GET /internal/agent-admin/catalog` 查看实际 draft_id、revision、digest 和工具绑定。验证已发布行为时将渠道设为 `release`。

## 离线评测

离线评测默认直接通过 Admin 内部接口（`AGENT_CONFIG_SOURCE_URL` + `AGENT_ADMIN_INTERNAL_TOKEN`）一次性拉取配置并冻结到当次运行，不再要求先导出本地 JSON 文件；评测结束时将本次冻结的快照写入输出目录的只读 `config-snapshot.json` 作为审计留痕。

```bash
cd duxue-server
# 默认读取 AGENT_CONFIG_CHANNEL（未设时为 working-draft）
.venv/bin/python -m evals run --case omni-politics-008
# 显式指定测试发布版
.venv/bin/python -m evals run --config-channel release --case omni-politics-008
# 本地数据集离线评测同样默认直连 Admin
.venv/bin/python -m evals.local run --config-channel working-draft --out var/evals/local-check --preflight-only
```

`evals`（托管评测）、`evals.local`（本地文件评测）和 `evals.exams.run` 均支持 `--config-channel working-draft|release`；入口在导入模型前从 Admin 拉取一次并冻结，同一进程所有线程使用同一不可变快照，`manifest.json` 记录 `config_source`、`config_id`、`config_revision` 和完整 `config_digest`。`--config-snapshot` 仅保留给单元测试或纯离线无网复现。`validate/export/compare` 数据集操作不要求 Agent 配置或在线 Admin；评测数据、标注继续由 Git 维护。

## 单测与部署验证

`tests/fixtures/`是明确隔离的历史回归输入，由`tests/conftest.py`显式安装；不随镜像发布，不是业务配置维护源。部署前执行`python -m app.agent_specs preflight`验证Admin发布或兼容缓存，失败保留原容器。初次生产接入步骤见[部署文档](../../docs/deployment.md#生产server接入admin配置)。

统一离线 runner 不再使用配置包中的旧 `evals.semantic-judge`，独立评分由 Langfuse 原生 Evaluator 承担；执行、快照与限制见[离线评测设计](../../docs/technical/eval-offline.md)。
