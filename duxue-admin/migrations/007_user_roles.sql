ALTER TABLE admin_users ADD COLUMN role text NOT NULL DEFAULT 'admin' CHECK(role IN ('visitor','admin'));
ALTER TABLE admin_users ALTER COLUMN role SET DEFAULT 'visitor';
