-- Configuration identity is the release/digest. Old wire artifacts are not upgraded.
ALTER TABLE agent_releases ALTER COLUMN debug_run_id DROP NOT NULL;
ALTER TABLE agent_debug_runs ADD COLUMN format_version integer NOT NULL DEFAULT 2;
ALTER TABLE agent_debug_runs ALTER COLUMN format_version SET DEFAULT 3;
UPDATE agent_drafts SET state='archived' WHERE state='working' AND bundle->>'format_version'<>'3';
UPDATE agent_environments e SET release_id=NULL,generation=generation+1
 WHERE release_id IS NOT NULL AND EXISTS(SELECT 1 FROM agent_releases r WHERE r.id=e.release_id AND r.bundle->>'format_version'<>'3');
