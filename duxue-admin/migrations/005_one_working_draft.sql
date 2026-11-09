-- Retain historical rows and evidence; expose at most one shared unpublished draft.
ALTER TABLE agent_drafts ADD COLUMN state text NOT NULL DEFAULT 'archived'
 CHECK(state IN ('working','published','archived'));
UPDATE agent_drafts d SET state='published'
 WHERE EXISTS(SELECT 1 FROM agent_releases r WHERE r.draft_id=d.id AND r.revision=d.revision);
WITH candidate AS (
 SELECT d.id FROM agent_drafts d
 WHERE d.state='archived' AND d.bundle->>'format_version'='2'
 AND d.validation->>'valid'='true'
 AND NOT EXISTS(SELECT 1 FROM agent_releases r WHERE r.draft_id=d.id AND r.revision=d.revision)
 AND (NOT EXISTS(SELECT 1 FROM agent_environments WHERE release_id IS NOT NULL)
      OR d.bundle->>'compatibility'=(SELECT r.bundle->>'compatibility' FROM agent_environments e JOIN agent_releases r ON r.id=e.release_id WHERE e.name='test'))
 ORDER BY d.updated_at DESC LIMIT 1
)
UPDATE agent_drafts SET state='working' WHERE id IN (SELECT id FROM candidate);
CREATE UNIQUE INDEX agent_one_working_draft ON agent_drafts ((true)) WHERE state='working';
ALTER TABLE agent_debug_runs ADD COLUMN base_release_id uuid REFERENCES agent_releases(id);
-- Only backfill the still-current exact revision; older bases are unknown.
UPDATE agent_debug_runs run SET base_release_id=d.base_release_id
 FROM agent_drafts d WHERE run.draft_id=d.id AND run.revision=d.revision;
