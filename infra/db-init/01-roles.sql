-- LOCAL DEV ONLY: runs once at first container init (docker-entrypoint-initdb.d).
-- Gives the runtime roles LOGIN with dev passwords matching apps/api/.env.example.
-- In prod (Neon) this step is the provisioning runbook with secret-managed passwords;
-- migrations only ever create/grant NOLOGIN roles.

CREATE ROLE cg_app LOGIN PASSWORD 'cg_app_dev_password';
CREATE ROLE cg_worker LOGIN PASSWORD 'cg_worker_dev_password';
