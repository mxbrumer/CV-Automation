-- Runs once on an empty data directory (docker-entrypoint-initdb.d) and again
-- from `scripts/dev.ps1 reset-db`. Idempotent: creates each DB only if missing.
-- Names come from the container env (POSTGRES_DB, LANGFLOW_DB).

\getenv app_db POSTGRES_DB
\getenv langflow_db LANGFLOW_DB

SELECT format('CREATE DATABASE %I', :'app_db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_db')\gexec

SELECT format('CREATE DATABASE %I', :'langflow_db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'langflow_db')\gexec
