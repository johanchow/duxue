# 读学 Server — Agent 导航

仓库根 [AGENTS.md](../AGENTS.md) 的铁律在这里继续有效。本文件只写服务端特有的归属和验收，不复述设计。

## 改动先对上唯一设计

| 要改的东西 | 先读 |
|---|---|
| Workflow 节点与边、Agent / Gate / Tool 定义、Prompt、模型参数、工具绑定、执行次数上限 | [Agent 与 Workflow 配置设计](../docs/technical/design-agent.md) |
| 草稿、校验、发布、回滚、隔离调试 | [配置管理台设计](../docs/technical/design-admin.md) |
| 本机怎么加载配置、离线评测冻结哪一版、单测夹具怎么更新 | [配置入口](agent_specs/README.md) |
| 当前运行图长什么样 | [现状流程图](../docs/technical/agent-flow-current.md)。它是导出视图，不是配置来源 |
| 分层、表、API、队列、测试目录 | [服务端设计](../docs/technical/design-server.md)；Context 清单以 [DDD 概览](../docs/technical/ddd-overview.md) 为准 |
| 某个 Context 的业务不变量 | 下表对应的 `domain-*.md` |
| 答疑质量、数据集、发布阈值 | [离线评测设计](../docs/technical/eval-offline.md) |
| 启动、迁移、联调库 | [服务端 README](README.md) |

| Context | 设计 |
|---|---|
| Companion 入口、Thread / Run | [domain-companion.md](../docs/technical/domain-companion.md) |
| 主动专注挑战（Sprint） | [domain-study.md](../docs/technical/domain-study.md) |
| Study | [domain-study.md](../docs/technical/domain-study.md) |
| Tutoring 教学事实与答案保护 | [domain-tutoring.md](../docs/technical/domain-tutoring.md) |
| 解题与辅导分链路 | [domain-problem-solving.md](../docs/technical/domain-problem-solving.md) |
| 回答形状与配图 | [domain-tutoring-presentation.md](../docs/technical/domain-tutoring-presentation.md) |
| Evaluation | [domain-evaluation.md](../docs/technical/domain-evaluation.md) |
| Memory | [domain-memory.md](../docs/technical/domain-memory.md) |
| 行为观察 | [domain-behavior.md](../docs/technical/domain-behavior.md) |

动手前先读 [.agent/notes/00-index.md](../.agent/notes/00-index.md) 里对应笔记。平台、配置加载和模型环境的决策记在 [platform.md](../.agent/notes/platform.md)，领域决策记在该领域笔记。

## 配置和代码各管什么

流程和可编辑配置的修改以 [design-agent.md](../docs/technical/design-agent.md) 为准，尤其是文首[配置铁律](../docs/technical/design-agent.md#配置铁律)。Admin 数据库是 Workflow、Agent、Gate、Tool 的唯一编辑入口。改本地 JSON、仓库夹具或运行缓存，都不能当作配置已交付。

代码继续持有这些，不能放进可编辑配置：

- `agent_specs/contracts.json`、`schemas/` 和 Python 契约校验器
- 已注册的处理器、条件函数、Context Builder
- 必经门禁、失败安全、执行次数和工具授权的上限
- 领域不变量、事务和写入权。Workflow 编排用例，不代替用例

模型输出只是候选。答案保护、越权和已确认业务事实仍由代码强制。Prompt 写通用规则；不为单道评测题或线上单题追加具体题目、字词或特例。开放语义交给模型或独立 Judge，不用关键词或正则裁决。

`AI_MODEL_OVERRIDES` 已停用。模型名在 Admin 发布包里改；端点、密钥和总开关留在环境变量。

## 代码放哪

生产代码只在 `app/`：`api` 接入，`application` 编排，`contexts/*/domain` 放不变量，`infrastructure` 放数据库、模型和外部适配，`workers` 只调用 application。`app/agent_specs/` 是运行时契约和加载，不是第二份可编辑流程。

一个 path 只注册一次。共享 HTTP 辅助放 `app/api/v1/common.py`，应用装配只在 `bootstrap`。

## 怎样算改完

行为变更带测试，用 `duxue-server/.venv` 里的 Python 和 pytest 跑相关用例。持久化结构还要按 [数据库与联调验收](README.md#数据库与联调验收) 核对 `.env` 指向的 PostgreSQL；SQLite 或一次性测试库通过，不能当作联调库已迁移。

Agent 配置变更的验收是 Admin 回读，加上实例加载回执里的 draft 或 release ID、revision 和 digest。需要新夹具时，先在 Admin 保存并校验，再按该版本导出到 `tests/fixtures/`。部署前跑 `python -m app.agent_specs preflight`。
