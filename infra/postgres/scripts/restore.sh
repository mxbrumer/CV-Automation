#!/bin/sh
# Used by `scripts/dev.ps1 restore`: drop both databases and load a dump made by backup.sh.
# The dump was made with --create, so the databases must not exist when it is loaded.
# Stop every client of the databases first (dev.ps1 does).
set -eu
dump="$1"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
  -c "DROP DATABASE IF EXISTS \"$LANGFLOW_DB\" WITH (FORCE)"
psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -f "$dump"
