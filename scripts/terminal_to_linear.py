#!/usr/bin/env python3
"""
Scan recent terminal output and create/update a Linear bug issue.

Usage:
  LINEAR_API_KEY=lin_api_xxx python3 scripts/terminal_to_linear.py
  LINEAR_API_KEY=lin_api_xxx python3 scripts/terminal_to_linear.py --terminal-file /path/to/220477.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx


LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
DEFAULT_TERMINALS_DIR = Path.home() / ".cursor" / "projects" / "Users-tim-Works-Owlynn" / "terminals"
ERROR_PATTERNS = (
    r"Traceback \(most recent call last\):",
    r"\bERROR\b",
    r"\bException\b",
    r"ModuleNotFoundError",
    r"Connection refused",
    r"npm error",
    r"Unhandled exception",
    r"failed",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create/update Linear bug from terminal errors.")
    parser.add_argument("--terminals-dir", type=Path, default=DEFAULT_TERMINALS_DIR)
    parser.add_argument("--terminal-file", type=Path, default=None)
    parser.add_argument("--tail-lines", type=int, default=240)
    parser.add_argument("--team", type=str, default="Winter152")
    parser.add_argument("--project", type=str, default="Owlynn")
    parser.add_argument("--labels", type=str, default="Bug,runtime")
    parser.add_argument("--dry-run", action="store_true", help="Print payload only, do not call Linear API.")
    return parser.parse_args()


def graphql_request(api_key: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=20) as client:
        response = client.post(
            LINEAR_GRAPHQL_URL,
            headers=headers,
            json={"query": query, "variables": variables},
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"Linear GraphQL error: {payload['errors']}")
    return payload["data"]


def read_terminal(path: Path) -> tuple[dict[str, str], list[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    metadata: dict[str, str] = {}
    if len(lines) >= 4 and lines[0].strip() == "---":
        idx = 1
        while idx < len(lines) and lines[idx].strip() != "---":
            raw = lines[idx]
            if ":" in raw:
                k, v = raw.split(":", 1)
                metadata[k.strip()] = v.strip().strip('"')
            idx += 1
        return metadata, lines[idx + 1 :]
    return metadata, lines


def newest_terminal_file(terminals_dir: Path) -> Path:
    files = sorted(terminals_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No terminal files found in {terminals_dir}")
    return files[0]


def detect_error(lines: list[str]) -> tuple[str, str, list[str]]:
    """Return (signature_line, fingerprint, evidence_lines)."""
    joined = "\n".join(lines)
    regex = re.compile("|".join(ERROR_PATTERNS), flags=re.IGNORECASE)
    matches = list(regex.finditer(joined))
    if not matches:
        raise ValueError("No recognizable error pattern found in terminal output.")

    # Use the first matched line as signature, include context around the last match for evidence.
    signature_line = ""
    for line in lines:
        if regex.search(line):
            signature_line = line.strip()
            break
    if not signature_line:
        signature_line = "Unclassified runtime failure"

    last_match_idx = 0
    for idx, line in enumerate(lines):
        if regex.search(line):
            last_match_idx = idx
    start = max(0, last_match_idx - 16)
    end = min(len(lines), last_match_idx + 40)
    evidence = lines[start:end]

    normalized = re.sub(r"\d+", "#", signature_line.lower())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    fingerprint = f"termerr-{digest}"
    return signature_line, fingerprint, evidence


def resolve_team(api_key: str, team_name: str) -> dict[str, Any]:
    query = """
    query TeamByName($name: String!) {
      teams(filter: { name: { eq: $name } }, first: 1) {
        nodes { id name key }
      }
    }
    """
    data = graphql_request(api_key, query, {"name": team_name})
    nodes = data["teams"]["nodes"]
    if not nodes:
        raise ValueError(f"Team '{team_name}' not found in Linear.")
    return nodes[0]


def resolve_project(api_key: str, project_name: str) -> dict[str, Any]:
    query = """
    query ProjectByName($name: String!) {
      projects(filter: { name: { eq: $name } }, first: 1) {
        nodes { id name }
      }
    }
    """
    data = graphql_request(api_key, query, {"name": project_name})
    nodes = data["projects"]["nodes"]
    if not nodes:
        raise ValueError(f"Project '{project_name}' not found in Linear.")
    return nodes[0]


def resolve_labels(api_key: str, team_id: str, label_names: list[str]) -> list[str]:
    if not label_names:
        return []
    query = """
    query TeamLabels($teamId: String!) {
      issueLabels(filter: { team: { id: { eq: $teamId } } }, first: 200) {
        nodes { id name }
      }
    }
    """
    data = graphql_request(api_key, query, {"teamId": team_id})
    by_name = {n["name"].strip().lower(): n["id"] for n in data["issueLabels"]["nodes"]}
    return [by_name[name.lower()] for name in label_names if name.lower() in by_name]


def find_existing_issue(api_key: str, team_id: str, project_id: str, fingerprint: str) -> dict[str, Any] | None:
    query = """
    query CandidateIssues($teamId: String!, $projectId: String!) {
      issues(
        filter: {
          team: { id: { eq: $teamId } }
          project: { id: { eq: $projectId } }
        }
        first: 80
      ) {
        nodes {
          id
          identifier
          title
          url
          state { type name }
        }
      }
    }
    """
    data = graphql_request(api_key, query, {"teamId": team_id, "projectId": project_id})
    for issue in data["issues"]["nodes"]:
        state_type = (issue.get("state") or {}).get("type", "")
        if state_type in {"completed", "canceled"}:
            continue
        if fingerprint in issue.get("title", ""):
            return issue
    return None


def create_issue(
    api_key: str,
    *,
    title: str,
    description: str,
    team_id: str,
    project_id: str,
    label_ids: list[str],
) -> dict[str, Any]:
    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue { id identifier title url }
      }
    }
    """
    issue_input: dict[str, Any] = {
        "title": title,
        "description": description,
        "teamId": team_id,
        "projectId": project_id,
        "priority": 2,
    }
    if label_ids:
        issue_input["labelIds"] = label_ids
    data = graphql_request(api_key, mutation, {"input": issue_input})
    return data["issueCreate"]["issue"]


def update_issue(api_key: str, issue_id: str, description: str, label_ids: list[str]) -> dict[str, Any]:
    mutation = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
        issue { id identifier title url }
      }
    }
    """
    issue_input: dict[str, Any] = {"description": description}
    if label_ids:
        issue_input["labelIds"] = label_ids
    data = graphql_request(api_key, mutation, {"id": issue_id, "input": issue_input})
    return data["issueUpdate"]["issue"]


def build_description(
    fingerprint: str,
    signature_line: str,
    terminal_file: Path,
    metadata: dict[str, str],
    evidence: list[str],
) -> str:
    cwd = metadata.get("cwd", "")
    command = metadata.get("command", metadata.get("last_command", ""))
    snippet = "\n".join(evidence[-80:])
    return (
        f"## Runtime error digest\n"
        f"- Fingerprint: `{fingerprint}`\n"
        f"- Signature: `{signature_line}`\n"
        f"- Source terminal file: `{terminal_file}`\n"
        f"- CWD: `{cwd}`\n"
        f"- Command: `{command}`\n\n"
        f"## Recent error snippet\n"
        f"```\n{snippet}\n```\n"
    )


def main() -> int:
    args = parse_args()
    api_key = (os.getenv("LINEAR_API_KEY") or "").strip()
    if not api_key:
        print("Error: LINEAR_API_KEY is required.", file=sys.stderr)
        return 2

    terminal_file = args.terminal_file or newest_terminal_file(args.terminals_dir)
    if not terminal_file.exists():
        print(f"Error: terminal file not found: {terminal_file}", file=sys.stderr)
        return 2

    metadata, body_lines = read_terminal(terminal_file)
    tail_lines = body_lines[-args.tail_lines :]
    try:
        signature_line, fingerprint, evidence = detect_error(tail_lines)
    except ValueError as e:
        print(str(e))
        return 0

    team = resolve_team(api_key, args.team)
    project = resolve_project(api_key, args.project)
    labels = [s.strip() for s in args.labels.split(",") if s.strip()]
    label_ids = resolve_labels(api_key, team["id"], labels)
    title = f"Bug: {fingerprint} - {signature_line[:80]}"
    description = build_description(fingerprint, signature_line, terminal_file, metadata, evidence)

    payload = {
        "team": team["name"],
        "project": project["name"],
        "title": title,
        "fingerprint": fingerprint,
        "labels": labels,
        "resolved_label_ids": label_ids,
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    existing = find_existing_issue(api_key, team["id"], project["id"], fingerprint)
    if existing:
        issue = update_issue(api_key, existing["id"], description, label_ids)
        print(f"Updated existing issue {issue['identifier']}: {issue['url']}")
    else:
        issue = create_issue(
            api_key,
            title=title,
            description=description,
            team_id=team["id"],
            project_id=project["id"],
            label_ids=label_ids,
        )
        print(f"Created issue {issue['identifier']}: {issue['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
