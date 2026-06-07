#!/usr/bin/env python3
"""Seed or delete the 50 assignment eval tickets in Jira.

Disable the Jira webhook before seeding so the agent does not triage new issues.

Examples:
  uv run python scripts/jira_eval_tickets.py seed
  uv run python scripts/jira_eval_tickets.py seed --dry-run
  uv run python scripts/jira_eval_tickets.py delete --dry-run
  uv run python scripts/jira_eval_tickets.py delete --yes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.eval_tickets import EVAL_TICKETS, EvalTicket
from rate_limit import bulk_mode_enabled, jira_request
from tools import _comment_adf_body, _jira_auth, _jira_base_url

load_dotenv(ROOT / ".env")

EVAL_SEED_LABEL = "eval-seed"
MANIFEST_PATH = ROOT / "eval" / "seeded_jira_issues.json"
SUMMARY_MAX_LEN = 255


@dataclass(frozen=True)
class SeededIssue:
    eval_id: str
    issue_key: str


@dataclass(frozen=True)
class SeedManifest:
    project_key: str
    issue_type: str
    label: str
    issues: tuple[SeededIssue, ...]


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _project_key(explicit: str | None) -> str:
    return (explicit or os.getenv("JIRA_PROJECT_KEY", "")).strip() or _require_env(
        "JIRA_PROJECT_KEY"
    )


def _issue_type(explicit: str | None) -> str:
    return (explicit or os.getenv("JIRA_ISSUE_TYPE", "Task")).strip() or "Task"


def summary_for(ticket: EvalTicket) -> str:
    """Build a Jira summary from an eval ticket id and body."""
    prefix = f"[{ticket.id}] "
    body = ticket.body.replace("\n", " ").strip()
    remaining = SUMMARY_MAX_LEN - len(prefix)
    if len(body) <= remaining:
        return f"{prefix}{body}"
    truncated = body[: max(remaining - 1, 0)].rstrip()
    return f"{prefix}{truncated}…"


def write_manifest(manifest: SeedManifest) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_key": manifest.project_key,
        "issue_type": manifest.issue_type,
        "label": manifest.label,
        "issues": [asdict(issue) for issue in manifest.issues],
    }
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_manifest() -> SeedManifest | None:
    if not MANIFEST_PATH.exists():
        return None
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    issues = tuple(
        SeededIssue(**issue) for issue in payload.get("issues", [])
    )
    return SeedManifest(
        project_key=str(payload["project_key"]),
        issue_type=str(payload.get("issue_type", "Task")),
        label=str(payload.get("label", EVAL_SEED_LABEL)),
        issues=issues,
    )


def create_issue(project_key: str, issue_type: str, ticket: EvalTicket) -> str:
    url = f"{_jira_base_url()}/rest/api/3/issue"
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary_for(ticket),
            "description": _comment_adf_body(ticket.body),
            "issuetype": {"name": issue_type},
            "labels": [EVAL_SEED_LABEL, ticket.id.lower()],
        }
    }
    response = jira_request(
        "POST",
        url,
        json=payload,
        auth=_jira_auth(),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code != 201:
        raise requests.HTTPError(
            f"Failed to create {ticket.id}: {response.status_code}: {response.text}"
        )
    return str(response.json()["key"])


def search_issue_keys(project_key: str, label: str) -> list[str]:
    url = f"{_jira_base_url()}/rest/api/3/search/jql"
    jql = f'project = {project_key} AND labels = "{label}" ORDER BY key ASC'
    keys: list[str] = []
    next_page_token: str | None = None

    while True:
        payload: dict[str, object] = {
            "jql": jql,
            "maxResults": 100,
            "fields": ["key"],
        }
        if next_page_token:
            payload["nextPageToken"] = next_page_token
        response = jira_request(
            "POST",
            url,
            json=payload,
            auth=_jira_auth(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )
        if response.status_code != 200:
            raise requests.HTTPError(
                f"Jira search failed: {response.status_code}: {response.text}"
            )

        data = response.json()
        issues = data.get("issues", [])
        for issue in issues:
            keys.append(str(issue["key"]))

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

    return keys


def delete_issue(issue_key: str) -> None:
    url = f"{_jira_base_url()}/rest/api/3/issue/{issue_key}"
    response = jira_request(
        "DELETE",
        url,
        params={"deleteSubtasks": "true"},
        auth=_jira_auth(),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if response.status_code != 204:
        raise requests.HTTPError(
            f"Failed to delete {issue_key}: {response.status_code}: {response.text}"
        )


def collect_delete_keys(
    project_key: str,
    label: str,
    *,
    use_manifest: bool,
) -> list[str]:
    if use_manifest:
        manifest = read_manifest()
        if manifest and manifest.issues:
            return [issue.issue_key for issue in manifest.issues]

    return search_issue_keys(project_key, label)


def _seed_parallelism(explicit: int | None) -> int:
    if explicit is not None:
        return max(1, explicit)
    return 10 if bulk_mode_enabled() else 1


def _seed_one(
    project_key: str,
    issue_type: str,
    ticket: EvalTicket,
) -> SeededIssue:
    issue_key = create_issue(project_key, issue_type, ticket)
    return SeededIssue(eval_id=ticket.id, issue_key=issue_key)


def cmd_seed(args: argparse.Namespace) -> int:
    project_key = _project_key(args.project)
    issue_type = _issue_type(args.issue_type)
    tickets = EVAL_TICKETS[: args.limit] if args.limit else EVAL_TICKETS
    parallel = _seed_parallelism(args.parallel)

    if args.dry_run:
        print(f"Would create {len(tickets)} issues in project {project_key}")
        print(f"Parallel Jira creates: {parallel}")
        for ticket in tickets:
            print(f"  {ticket.id}: {summary_for(ticket)}")
        print(f"Manifest would be written to {MANIFEST_PATH}")
        return 0

    created: list[SeededIssue] = []
    print(
        f"Creating {len(tickets)} eval tickets in {project_key} "
        f"(parallel={parallel}) ..."
    )

    if parallel <= 1:
        for index, ticket in enumerate(tickets, start=1):
            seeded = _seed_one(project_key, issue_type, ticket)
            created.append(seeded)
            print(f"  [{index}/{len(tickets)}] {ticket.id} -> {seeded.issue_key}")
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(_seed_one, project_key, issue_type, ticket): ticket
                for ticket in tickets
            }
            done = 0
            for future in as_completed(futures):
                ticket = futures[future]
                seeded = future.result()
                created.append(seeded)
                done += 1
                print(
                    f"  [{done}/{len(tickets)}] {ticket.id} -> {seeded.issue_key}"
                )

    created.sort(key=lambda issue: issue.eval_id)

    write_manifest(
        SeedManifest(
            project_key=project_key,
            issue_type=issue_type,
            label=EVAL_SEED_LABEL,
            issues=tuple(created),
        )
    )
    print(f"Wrote manifest: {MANIFEST_PATH}")
    print("Done.")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    project_key = _project_key(args.project)
    label = args.label
    keys = collect_delete_keys(
        project_key,
        label,
        use_manifest=not args.ignore_manifest,
    )

    if not keys:
        print("No seeded eval tickets found to delete.")
        return 0

    if args.dry_run:
        print(f"Would delete {len(keys)} issues:")
        for key in keys:
            print(f"  {key}")
        return 0

    if not args.yes:
        print(f"Refusing to delete {len(keys)} issues without --yes.")
        print("Run with --dry-run first to preview, then delete --yes.")
        return 1

    print(f"Deleting {len(keys)} issues ...")
    for index, issue_key in enumerate(keys, start=1):
        delete_issue(issue_key)
        print(f"  [{index}/{len(keys)}] deleted {issue_key}")

    if MANIFEST_PATH.exists() and not args.keep_manifest:
        MANIFEST_PATH.unlink()
        print(f"Removed manifest: {MANIFEST_PATH}")

    print("Done.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed or delete the 50 assignment eval tickets in Jira."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed = subparsers.add_parser("seed", help="Create all eval tickets in Jira")
    seed.add_argument("--project", help="Jira project key (or JIRA_PROJECT_KEY)")
    seed.add_argument(
        "--issue-type",
        help='Jira issue type name (default: JIRA_ISSUE_TYPE or "Task")',
    )
    seed.add_argument(
        "--limit",
        type=int,
        help="Create only the first N eval tickets (for smoke tests)",
    )
    seed.add_argument(
        "--parallel",
        type=int,
        default=None,
        help="Parallel Jira creates (default: 10 with EVAL_BULK_MODE, else 1)",
    )
    seed.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned issues without calling Jira",
    )
    seed.set_defaults(func=cmd_seed)

    delete = subparsers.add_parser(
        "delete", help="Delete seeded eval tickets from Jira"
    )
    delete.add_argument("--project", help="Jira project key (or JIRA_PROJECT_KEY)")
    delete.add_argument(
        "--label",
        default=EVAL_SEED_LABEL,
        help=f'Label used to find seeded tickets (default: {EVAL_SEED_LABEL})',
    )
    delete.add_argument(
        "--ignore-manifest",
        action="store_true",
        help="Find tickets by label instead of eval/seeded_jira_issues.json",
    )
    delete.add_argument(
        "--keep-manifest",
        action="store_true",
        help="Keep eval/seeded_jira_issues.json after deletion",
    )
    delete.add_argument(
        "--dry-run",
        action="store_true",
        help="List issues that would be deleted",
    )
    delete.add_argument(
        "--yes",
        action="store_true",
        help="Required to perform deletion",
    )
    delete.set_defaults(func=cmd_delete)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except requests.HTTPError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
