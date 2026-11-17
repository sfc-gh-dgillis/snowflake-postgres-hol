#!/usr/bin/env python3
"""
workspace_notebook - deploy the companion notebook to a Snowflake Workspace

Snowflake no longer allows new legacy notebooks (`snow notebook deploy`), so the
generated .ipynb is uploaded to a private workspace instead and opened as a
Notebook in Workspaces:

  USER$.PUBLIC.<DEMO_NOTEBOOK_NAME>    (personal workspace of the connected user)

Wraps the Snowflake CLI, so it reuses the auth of your CLI_CONNECTION_NAME
connection. Uses only workspace SQL (CREATE WORKSPACE, PUT to snow://workspace,
ALTER WORKSPACE ... COMMIT), so no extra tooling is needed.

Commands:
  deploy NOTEBOOK_FILE   create the workspace if needed, upload the file, publish it
  url NOTEBOOK_FILE      print the Snowsight URL of the uploaded notebook
  drop                   drop the workspace (requires --yes)

Configuration is read from the environment (.env/mirror.env, loaded by Task).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKSPACE_DATABASE = "USER$"
WORKSPACE_SCHEMA = "PUBLIC"
# Returned by ADD LIVE VERSION when an uncommitted live version is left over
# from an earlier run; uploading into it is fine.
LIVE_VERSION_EXISTS = "099106"


class LabError(Exception):
    """An expected failure with a user-facing message."""


def env(name: str, default: Optional[str] = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise LabError(f"{name} is not set (see .env/mirror.env)")
    return value


def workspace_fqn() -> str:
    return f"{WORKSPACE_DATABASE}.{WORKSPACE_SCHEMA}.{env('DEMO_NOTEBOOK_NAME')}"


def workspace_uri() -> str:
    return f"snow://workspace/{workspace_fqn()}/versions/head/"


def _parse_json_rows(stdout: str) -> List[Dict[str, Any]]:
    """Parse `snow sql --format JSON` output, tolerating leading non-JSON lines."""
    starts = [i for i in (stdout.find("["), stdout.find("{")) if i >= 0]
    if not starts:
        return []
    data, _ = json.JSONDecoder().raw_decode(stdout[min(starts):])
    if isinstance(data, dict):
        data = [data]
    rows = []
    for item in data:
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list):  # multi-statement output: list of result sets
            rows.extend(r for r in item if isinstance(r, dict))
    return rows


def run_snow_sql(query: str, ignore_codes: tuple = ()) -> List[Dict[str, Any]]:
    """Run ONE statement and return its rows. Errors whose code is in ignore_codes are skipped."""
    cmd = [
        "snow", "sql",
        "--connection", env("CLI_CONNECTION_NAME"),
        "--role", env("MIRROR_ADMIN_ROLE_NAME"),
        "--format", "JSON",
        "--enable-templating", "NONE",
        "-q", query,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise LabError("snow CLI not found. Install it: "
                       "https://docs.snowflake.com/en/developer-guide/snowflake-cli/installation/installation")
    if result.returncode != 0:
        output = result.stderr.strip() or result.stdout.strip()
        if any(code in output for code in ignore_codes):
            return []
        raise LabError("Snowflake command failed:\n" + output)
    return _parse_json_rows(result.stdout)


def notebook_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_file():
        raise LabError(f"Notebook file not found: {path} (run the generate-notebook task first)")
    return path


def snowsight_url(file_name: str) -> str:
    rows = run_snow_sql("SELECT CURRENT_ORGANIZATION_NAME() AS ORG, "
                        "CURRENT_ACCOUNT_NAME() AS ACCOUNT, CURRENT_REGION() AS REGION")
    if not rows:
        raise LabError("Could not read the current organization and account")
    row = {str(k).upper(): v for k, v in rows[0].items()}
    host = ("https://preprod.app.snowflake.com" if "PREPROD" in str(row["REGION"]).upper()
            else "https://app.snowflake.com")
    segments = [WORKSPACE_DATABASE, WORKSPACE_SCHEMA, env("DEMO_NOTEBOOK_NAME")]
    path = "/".join(s.replace("$", "%24") for s in segments)
    return f"{host}/{row['ORG']}/{row['ACCOUNT']}/#/workspaces/ws/{path}/{file_name}"


def cmd_deploy(args: argparse.Namespace) -> None:
    path = notebook_path(args.notebook_file)
    fqn = workspace_fqn()
    print(f"Deploying {path.name} to workspace {fqn}...")
    run_snow_sql(f"CREATE WORKSPACE IF NOT EXISTS {fqn}")
    # PUT and COMMIT need a live version; reuse one left over from an interrupted run.
    run_snow_sql(f"ALTER WORKSPACE {fqn} ADD LIVE VERSION FROM LAST",
                 ignore_codes=(LIVE_VERSION_EXISTS,))
    local = str(path).replace("'", "\\'")
    rows = run_snow_sql(f"PUT 'file://{local}' '{workspace_uri()}' "
                        "AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
    statuses = {str({k.lower(): v for k, v in r.items()}.get("status", "")).upper() for r in rows}
    if not statuses & {"UPLOADED", "SKIPPED"}:
        raise LabError(f"Upload of {path.name} did not report UPLOADED: {rows}")
    run_snow_sql(f"ALTER WORKSPACE {fqn} COMMIT")
    print(f"✓ Notebook uploaded to workspace {fqn}")


def cmd_url(args: argparse.Namespace) -> None:
    print(snowsight_url(Path(args.notebook_file).name))


def cmd_drop(args: argparse.Namespace) -> None:
    if not args.yes:
        raise LabError("Refusing to drop the workspace without --yes")
    fqn = workspace_fqn()
    run_snow_sql(f"DROP WORKSPACE IF EXISTS {fqn}")
    print(f"✓ Dropped workspace {fqn} (if it existed)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the companion notebook to a Snowflake Workspace")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("deploy", help="create the workspace if needed, upload the notebook, publish it")
    p.add_argument("notebook_file", help="path to the generated .ipynb")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("url", help="print the Snowsight URL of the notebook")
    p.add_argument("notebook_file", help="path (or name) of the generated .ipynb")
    p.set_defaults(func=cmd_url)

    p = sub.add_parser("drop", help="drop the workspace")
    p.add_argument("--yes", action="store_true", help="confirm the drop")
    p.set_defaults(func=cmd_drop)

    args = parser.parse_args()
    try:
        args.func(args)
    except LabError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
