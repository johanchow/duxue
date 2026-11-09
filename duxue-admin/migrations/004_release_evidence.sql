ALTER TABLE agent_debug_runs ADD CONSTRAINT debug_run_snapshot UNIQUE(id,draft_id,revision,digest);
ALTER TABLE agent_releases ADD CONSTRAINT release_debug_snapshot
 FOREIGN KEY(debug_run_id,draft_id,revision,digest)
 REFERENCES agent_debug_runs(id,draft_id,revision,digest);
