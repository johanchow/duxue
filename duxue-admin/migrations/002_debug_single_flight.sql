CREATE UNIQUE INDEX admin_single_debug ON agent_debug_runs(created_by) WHERE status='running';
