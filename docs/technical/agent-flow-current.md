# 当前 Agent 流程图（自动生成）

> 由 `duxue-server/agent_specs/workflows/*.json` 生成；编辑定义后运行 `cd duxue-server && .venv/bin/python -m app.agent_specs export`。
> 实线表示主要执行路径，虚线表示节点内部的条件步骤；门禁实际执行条件仍由代码裁决。
> 独立 API 调用有各自的 Workflow；未连接的节点表示会话外阶段。

## companion · v1

```mermaid
flowchart TD
  companion_START([START])
  companion_END([END])
  companion_intent_route[companion.intent_route]
  companion_switch_confirm{companion.switch_confirm}
  companion_final_route[companion.final_route]
  companion_START --> companion_intent_route
  companion_intent_route -->|cross_scene| companion_switch_confirm
  companion_intent_route -->|direct| companion_final_route
  companion_switch_confirm --> companion_final_route
  companion_final_route --> companion_END
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |
| `companion.intent@v7` | `qwen-flash` | `companion.intent.system.v7` |
| `companion.scene-switch@v1` | `qwen3.8-flash` | `companion.scene-switch.system.v1` |

工具：无。

## planning · v1

```mermaid
flowchart TD
  planning_START([START])
  planning_END([END])
  planning_prepare_review[planning.prepare_review]
  planning_route_after_prepare[planning.route_after_prepare]
  planning_wait_for_confirmation[planning.wait_for_confirmation]
  planning_confirmation_gate{planning.confirmation_gate}
  planning_checkpointer_connect[planning.checkpointer_connect]
  planning_checkpointer_setup[planning.checkpointer_setup]
  planning_context_build[planning.context_build]
  planning_plan_intake[planning.plan_intake]
  planning_agent_text[planning.agent_text]
  planning_graph_compile[planning.graph_compile]
  planning_graph_invoke[planning.graph_invoke]
  planning_START --> planning_prepare_review
  planning_prepare_review -->|review| planning_wait_for_confirmation
  planning_prepare_review -->|finish| planning_END
  planning_wait_for_confirmation --> planning_confirmation_gate
  planning_confirmation_gate --> planning_END
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |
| `planning.intake@v2` | `qwen3.7-plus-2026-05-26` | `planning.intake.prompt.v3` |
| `planning.reply@v2` | `qwen3.8-flash` | `companion.agent-text.system.v2` |

工具：无。

## reflection · v1

```mermaid
flowchart TD
  reflection_START([START])
  reflection_END([END])
  reflection_turn[reflection.turn]
  reflection_START --> reflection_turn
  reflection_turn --> reflection_END
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |

工具：无。

## review-aspects · v1

```mermaid
flowchart TD
  review_aspects_START([START])
  review_aspects_END([END])
  review_aspects_run[review-aspects.run]
  review_aspects_START --> review_aspects_run
  review_aspects_run --> review_aspects_END
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |
| `evaluation.review-aspects@v1` | `qwen-flash` | `evaluation.review-aspects.system.v1` |

工具：无。

## task-intake · v1

```mermaid
flowchart TD
  task_intake_START([START])
  task_intake_END([END])
  task_intake_run[task-intake.run]
  task_intake_START --> task_intake_run
  task_intake_run --> task_intake_END
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |
| `task.intake@v1` | `qwen3.7-plus-2026-05-26` | `task.intake.prompt.v2` |

工具：无。

## tutoring-retry · v1

```mermaid
flowchart TD
  tutoring_retry_START([START])
  tutoring_retry_END([END])
  tutoring_retry_primary[tutoring-retry.primary]
  tutoring_retry_repair[tutoring-retry.repair]
  tutoring_retry_backup[tutoring-retry.backup]
  tutoring_retry_visual_decision[tutoring-retry.visual_decision]
  tutoring_retry_visual_redraw[tutoring-retry.visual_redraw]
  tutoring_retry_missing_decision[tutoring-retry.missing_decision]
  tutoring_retry_missing_primary[tutoring-retry.missing_primary]
  tutoring_retry_missing_backup[tutoring-retry.missing_backup]
  tutoring_retry_finish[tutoring-retry.finish]
  tutoring_retry_START --> tutoring_retry_primary
  tutoring_retry_primary -->|no_candidate| tutoring_retry_finish
  tutoring_retry_primary -->|retry_leak| tutoring_retry_repair
  tutoring_retry_primary -->|candidate_without_retry| tutoring_retry_visual_decision
  tutoring_retry_repair -->|same_leak_with_backup| tutoring_retry_backup
  tutoring_retry_repair -->|no_backup_needed| tutoring_retry_visual_decision
  tutoring_retry_backup --> tutoring_retry_visual_decision
  tutoring_retry_visual_decision -->|needs_visual_redraw| tutoring_retry_visual_redraw
  tutoring_retry_visual_decision -->|no_visual_redraw| tutoring_retry_missing_decision
  tutoring_retry_visual_redraw --> tutoring_retry_missing_decision
  tutoring_retry_missing_decision -->|needs_missing_visual| tutoring_retry_missing_primary
  tutoring_retry_missing_decision -->|no_missing_visual| tutoring_retry_finish
  tutoring_retry_missing_primary -->|retry_missing_with_backup| tutoring_retry_missing_backup
  tutoring_retry_missing_primary -->|missing_attempt_done| tutoring_retry_finish
  tutoring_retry_missing_backup --> tutoring_retry_finish
  tutoring_retry_finish --> tutoring_retry_END
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |

工具：无。

## tutoring-vet · v1

```mermaid
flowchart TD
  tutoring_vet_START([START])
  tutoring_vet_END([END])
  tutoring_vet_authority{tutoring-vet.authority}
  tutoring_vet_text_leak{tutoring-vet.text_leak}
  tutoring_vet_visual_leak{tutoring-vet.visual_leak}
  tutoring_vet_complete[tutoring-vet.complete]
  tutoring_vet_START --> tutoring_vet_authority
  tutoring_vet_authority -->|authority_denied| tutoring_vet_complete
  tutoring_vet_authority -->|authority_allowed_needs_leak_check| tutoring_vet_text_leak
  tutoring_vet_authority -->|authority_allowed_no_leak_check| tutoring_vet_complete
  tutoring_vet_text_leak -->|text_denied| tutoring_vet_complete
  tutoring_vet_text_leak -->|text_allowed_with_visual| tutoring_vet_visual_leak
  tutoring_vet_text_leak -->|text_allowed_no_visual| tutoring_vet_complete
  tutoring_vet_visual_leak --> tutoring_vet_complete
  tutoring_vet_complete --> tutoring_vet_END
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |
| `tutoring.leak-judge@v8` | `qwen3.8-flash` | `tutoring.leak-judge.system.v7` |
| `tutoring.visual-leak-judge@v5` | `qwen-plus` | `tutoring.visual-leak-judge.system.v5` |

工具：无。

## tutoring · v1

```mermaid
flowchart TD
  tutoring_START([START])
  tutoring_END([END])
  tutoring_turn[tutoring.turn]
  tutoring_image_target[tutoring.image_target]
  tutoring_model_loop[tutoring.model_loop]
  tutoring_attempt[tutoring.attempt]
  tutoring_tool_budget{tutoring.tool_budget}
  tutoring_candidate_schema{tutoring.candidate_schema}
  tutoring_visual_schema{tutoring.visual_schema}
  tutoring_exit_gate[tutoring.exit_gate]
  tutoring_candidate_exit{tutoring.candidate_exit}
  tutoring_visual{tutoring.visual}
  tutoring_output_safety{tutoring.output_safety}
  tutoring_apply_problem[tutoring.apply_problem]
  tutoring_result[tutoring.result]
  tutoring_START --> tutoring_turn
  tutoring_turn -->|image_reference| tutoring_image_target
  tutoring_turn -->|ready| tutoring_model_loop
  tutoring_image_target -->|resolved| tutoring_model_loop
  tutoring_model_loop --> tutoring_attempt
  tutoring_attempt -->|candidate| tutoring_exit_gate
  tutoring_exit_gate -->|retry| tutoring_attempt
  tutoring_exit_gate -->|checked| tutoring_output_safety
  tutoring_output_safety -->|accepted_work| tutoring_apply_problem
  tutoring_output_safety -->|fallback_or_readonly| tutoring_result
  tutoring_apply_problem --> tutoring_result
  tutoring_result --> tutoring_END
  tutoring_attempt -.-> tutoring_tool_budget
  tutoring_attempt -.-> tutoring_candidate_schema
  tutoring_attempt -.-> tutoring_visual_schema
  tutoring_exit_gate -.-> tutoring_candidate_exit
  tutoring_exit_gate -.-> tutoring_visual
```

| 组件 | 模型 | Prompt |
| --- | --- | --- |
| `tutoring.image-target@v1` | `qwen3.8-flash` | `tutoring.image-target.system.v1` |
| `tutoring.turn@v19` | `qwen3.7-plus-2026-05-26` | `tutoring.turn.system.v19` |
| `tutoring.turn-backup@v2` | `qwen3.8-flash` | `tutoring.turn.system.v19` |

工具：`tutoring.get_attempt_summary`, `tutoring.get_task_context`, `tutoring.lookup_history`, `tutoring.widget_guidelines`。

具体 Prompt 正文：`cd duxue-server && .venv/bin/python -m app.agent_specs show <agent>`。
