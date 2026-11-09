CREATE TABLE admin_users (
 id uuid PRIMARY KEY, email text NOT NULL UNIQUE, password_hash text NOT NULL,
 active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE admin_sessions (
 token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES admin_users(id),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX admin_sessions_expiry ON admin_sessions(expires_at);
CREATE TABLE admin_login_attempts (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, key_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX admin_login_attempts_window ON admin_login_attempts(key_hash,created_at);
CREATE TABLE agent_drafts (
 id uuid PRIMARY KEY, title text NOT NULL, bundle jsonb NOT NULL,
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0), validation jsonb,
 created_by uuid NOT NULL REFERENCES admin_users(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE agent_debug_runs (
 id uuid PRIMARY KEY, draft_id uuid NOT NULL REFERENCES agent_drafts(id), revision integer NOT NULL,
 digest text NOT NULL, input jsonb NOT NULL, status text NOT NULL CHECK(status IN ('running','succeeded','blocked','failed','interrupted')),
 result jsonb, error text, created_by uuid NOT NULL REFERENCES admin_users(id),
 started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
);
CREATE INDEX agent_debug_draft ON agent_debug_runs(draft_id,revision,started_at DESC);
CREATE TABLE agent_releases (
 id uuid PRIMARY KEY, sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 draft_id uuid NOT NULL REFERENCES agent_drafts(id), revision integer NOT NULL,
 digest text NOT NULL, bundle jsonb NOT NULL, validation jsonb NOT NULL,
 debug_run_id uuid NOT NULL REFERENCES agent_debug_runs(id),
 created_by uuid NOT NULL REFERENCES admin_users(id), created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(draft_id,revision,digest)
);
CREATE FUNCTION immutable_agent_release() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Agent releases are immutable'; END $$;
CREATE TRIGGER immutable_agent_release BEFORE UPDATE OR DELETE ON agent_releases
FOR EACH ROW EXECUTE FUNCTION immutable_agent_release();
CREATE TABLE agent_environments (
 name text PRIMARY KEY CHECK(name='test'), release_id uuid REFERENCES agent_releases(id),
 generation bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO agent_environments(name) VALUES ('test');
CREATE TABLE agent_server_instances (
 instance_id text PRIMARY KEY, release_id uuid REFERENCES agent_releases(id), digest text,
 status text NOT NULL CHECK(status IN ('loaded','failed')), error text,
 last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE admin_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, actor_id uuid REFERENCES admin_users(id),
 action text NOT NULL, target_id uuid, details jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now()
);
