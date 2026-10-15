#!/usr/bin/env python3
"""Delete Phoenix traces older than N days (plan 10, docs/governance.md). Standard library only.

    python scripts/prune_traces.py [--days 90] [--url http://127.0.0.1:6006] [--project NAME] [--dry-run]

Traces hold CV and posting text, so they are pruned like any other personal data. Phoenix also
applies PHOENIX_DEFAULT_RETENTION_POLICY_DAYS on its own; this is the on-demand version.
"""

import argparse
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta


def call(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def old_trace_ids(base: str, project: str, cutoff: datetime) -> set[str]:
    ids: set[str] = set()
    cursor = None
    while True:
        query = {"limit": 1000, "end_time": cutoff.isoformat()}
        if cursor:
            query["cursor"] = cursor
        page = call(f"{base}/v1/projects/{urllib.parse.quote(project)}/spans?" + urllib.parse.urlencode(query))
        ids.update(span["context"]["trace_id"] for span in page["data"])
        cursor = page.get("next_cursor")
        if not cursor:
            return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--url", default="http://127.0.0.1:6006")
    parser.add_argument("--project", help="only this Phoenix project (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cutoff = datetime.now(UTC) - timedelta(days=args.days)
    total = 0
    for project in call(f"{args.url}/v1/projects")["data"]:
        if args.project and project["name"] != args.project:
            continue
        ids = sorted(old_trace_ids(args.url, project["name"], cutoff))
        print(f"{project['name']}: {len(ids)} trace(s) older than {args.days} days")
        total += len(ids)
        if args.dry_run:
            continue
        # REST trace ids are OpenTelemetry ids; deleteTraces wants Phoenix's GraphQL ids.
        lookup = "query($p:ID!,$t:ID!){node(id:$p){... on Project{trace(traceId:$t){id}}}}"
        gql_ids = []
        for trace_id in ids:
            found = call(
                f"{args.url}/graphql",
                {"query": lookup, "variables": {"p": project["id"], "t": trace_id}},
            )["data"]["node"]["trace"]
            if found:
                gql_ids.append(found["id"])
        for start in range(0, len(gql_ids), 100):
            call(
                f"{args.url}/graphql",
                {
                    "query": "mutation($t:[ID!]!){deleteTraces(traceIds:$t){__typename}}",
                    "variables": {"t": gql_ids[start : start + 100]},
                },
            )
    print(f"{'would delete' if args.dry_run else 'deleted'} {total} trace(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
