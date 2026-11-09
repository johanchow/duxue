-- Each database owns one environment; test and prod never share a database.
ALTER TABLE agent_environments DROP CONSTRAINT agent_environments_name_check;
ALTER TABLE agent_environments ADD CONSTRAINT agent_environments_name_check CHECK(name IN ('test','prod'));
CREATE UNIQUE INDEX agent_single_environment ON agent_environments((true));
