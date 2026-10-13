-- Used by `scripts/dev.ps1 reset-db`: drop both databases, then recreate them
-- with the same init script a fresh container runs.

\getenv app_db POSTGRES_DB
\getenv langflow_db LANGFLOW_DB

SELECT format('DROP DATABASE IF EXISTS %I WITH (FORCE)', :'app_db')\gexec
SELECT format('DROP DATABASE IF EXISTS %I WITH (FORCE)', :'langflow_db')\gexec

\i /docker-entrypoint-initdb.d/01-databases.sql
