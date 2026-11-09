ALTER TABLE agent_debug_runs ADD COLUMN source_kind text CHECK(source_kind IN ('draft','release'));
ALTER TABLE agent_debug_runs ADD COLUMN target_kind text CHECK(target_kind IN ('agent','workflow'));
ALTER TABLE agent_debug_runs ADD COLUMN target_id text;
ALTER TABLE agent_debug_runs ADD COLUMN bundle jsonb;
