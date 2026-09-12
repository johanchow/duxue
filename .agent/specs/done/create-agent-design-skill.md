---
slug: create-agent-design-skill
created: 2026-09-12T01:53:13Z
status: done
---

# create-agent-design-skill spec

## 做什么 / 为什么
在 `.cursor/skills/agent-design/` 创建可复制到其他项目的通用 Agent 设计 Skill。它应引导 AI 产出可实施、可验证的技术设计文档，覆盖控制权、状态、工具、协作、可靠性、安全与评测；不包含本项目业务、架构或厂商/框架绑定规则。

## 验收标准
- [x] 目录包含可发现的 `SKILL.md`，其 frontmatter 使用 `agent-design` 名称和可区分的触发描述；正文只包含通用 Agent 设计工作流与边界。
- [x] 提供按需引用的通用设计文档模板、决策框架和审查清单；三者不出现项目名、领域名、实现语言或特定 Agent 框架的硬性依赖。
- [x] Skill 要求在设计前发现目标项目的真实约束，区分确定性业务控制与 LLM 决策，要求结构化契约、状态所有权、副作用控制、恢复与评测。
- [x] `skill-creator` 的 quick validator 通过，且以独立的文本检查确认所有引用文件存在、没有未替换脚手架或项目特定内容。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `.cursor/skills/agent-design/SKILL.md`：Skill 入口，定义适用范围、通用设计流程、文档交付与引用路由。
  - `.cursor/skills/agent-design/references/design-document-template.md`：可实施 Agent 设计文档的章节与契约表模板。
  - `.cursor/skills/agent-design/references/decision-framework.md`：以决策条件描述 workflow、Agent loop、状态、工具、协作、可靠性等选型，不绑定框架。
  - `.cursor/skills/agent-design/references/review-checklist.md`：交付前的完整性、边界与可靠性审查项。
  - `.agent/notes/043-agent-design-skill.md`：沉淀通用性边界与资源分层的设计决定。
- 测试计划：
  - 运行 `/Users/zzrzhou/.codex/skills/.system/skill-creator/scripts/quick_validate.py .cursor/skills/agent-design` 验证 Skill 结构、frontmatter 与占位符。
  - 用 `rg` 验证入口所链接的 reference 均存在，并扫描目标目录中是否出现 `duxue`、陪学等项目特定术语。
  - 审阅 `git diff --check` 与目标文件内容，确认引用为渐进披露而非重复/冲突规则。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 编写通用入口与三个按需 reference。
- [x] 写入设计决策笔记。
- [x] 执行结构/通用性验证、diff 审阅，并完成验收清单。

## 备注
