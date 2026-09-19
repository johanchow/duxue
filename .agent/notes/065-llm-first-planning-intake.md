# LLM-first Planning intake

日期：2026-09-18

- v1.5 removes text-based duration short-circuiting. Every non-structured Ward message reaches one `PlanIntake` LLM call with the active clarification slots as context.
- The model returns both `slot_updates` and schedule items, so a single utterance can update duration and start time. The service only validates, resolves Task references and writes structured results.
- `slot_id` form replies remain a direct protocol path, but they re-enter the Planning review graph before a confirm action is issued; an action can no longer be signed against a non-interrupt checkpoint.
