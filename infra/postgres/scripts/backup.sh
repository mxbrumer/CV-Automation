#!/bin/sh
# Used by `scripts/dev.ps1 backup`: dump both databases into one file.
# --create makes it restorable with: psql -U "$POSTGRES_USER" -d postgres -f <file>
set -eu
out="$1"
pg_dump -U "$POSTGRES_USER" --create "$POSTGRES_DB" > "$out.tmp"
pg_dump -U "$POSTGRES_USER" --create "$LANGFLOW_DB" >> "$out.tmp"
mv "$out.tmp" "$out"
