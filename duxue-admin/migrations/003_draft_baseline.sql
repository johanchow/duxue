ALTER TABLE agent_drafts ADD COLUMN base_bundle jsonb;
ALTER TABLE agent_drafts ADD COLUMN base_release_id uuid REFERENCES agent_releases(id);
-- Existing drafts have no recorded creation snapshot; do not invent one.
