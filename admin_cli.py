"""
TopGun Admin CLI Tool

Manage competition modes, teams, quotas, import custom keys, and export submission files.

Usage Examples:
    python admin_cli.py get-mode
    python admin_cli.py set-mode train
    python admin_cli.py set-mode test
    python admin_cli.py add-team "Alpha Squad" --token "my_custom_secret_key" --quota 5
    python admin_cli.py import-csv keys.csv --quota 5
    python admin_cli.py edit-team <team_id> --name "New Alpha" --token "new_key_123" --quota 10
    python admin_cli.py list-teams
    python admin_cli.py stats
    python admin_cli.py export-data --output all_submissions.zip
"""

import argparse
import csv
from pathlib import Path
import httpx

from app.config import settings

DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_ADMIN_KEY = settings.ADMIN_API_KEY


def get_client(url: str, admin_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=url.rstrip("/"),
        headers={"X-Admin-Key": admin_key},
        timeout=60.0
    )


def cmd_get_mode(args):
    with get_client(args.url, args.admin_key) as client:
        resp = client.get("/api/v1/admin/mode")
        if resp.status_code == 200:
            print(f"[+] Current Global Mode: {resp.json().get('global_mode')}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_set_mode(args):
    with get_client(args.url, args.admin_key) as client:
        resp = client.post("/api/v1/admin/mode", json={"mode": args.mode})
        if resp.status_code == 200:
            print(f"[+] Global Mode updated to: {args.mode.upper()}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_add_team(args):
    with get_client(args.url, args.admin_key) as client:
        payload = {"name": args.name}
        if args.quota is not None:
            payload["test_quota_limit"] = args.quota
        if args.token:
            payload["custom_token"] = args.token

        resp = client.post("/api/v1/admin/teams", json=payload)
        if resp.status_code == 200:
            data = resp.json()
            print("[+] Team Created Successfully!")
            print(f"    Name:        {data['name']}")
            print(f"    Team ID:     {data['team_id']}")
            print(f"    Test Quota:  {data['test_quota_limit']}")
            print(f"    SECRET TOKEN: {data['token']}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_edit_team(args):
    with get_client(args.url, args.admin_key) as client:
        payload = {}
        if args.name:
            payload["name"] = args.name
        if args.token:
            payload["custom_token"] = args.token
        if args.quota is not None:
            payload["test_quota_limit"] = args.quota
        if args.active is not None:
            payload["is_active"] = args.active

        resp = client.post(f"/api/v1/admin/teams/{args.team_id}/edit", json=payload)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[+] Team '{data['name']}' ({data['team_id']}) Updated Successfully!")
            print(f"    Token Prefix: {data['token_prefix']}")
            print(f"    Test Quota:   {data['test_quota_limit']}")
            print(f"    Is Active:    {data['is_active']}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_import_csv(args):
    csv_file = Path(args.file)
    if not csv_file.exists():
        print(f"[-] File not found: {csv_file}")
        return

    with open(csv_file, "r", encoding="utf-8-sig") as f:
        # Detect delimiter
        sample = f.read(2048)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ","

        reader = csv.DictReader(f, delimiter=delimiter)
        fieldnames = reader.fieldnames or []

        # Find columns
        name_col = args.name_col
        if not name_col:
            for c in fieldnames:
                if any(k in c.lower() for k in ["name", "team", "id"]):
                    name_col = c
                    break

        key_col = args.key_col
        if not key_col:
            for c in fieldnames:
                if any(k in c.lower() for k in ["key", "token", "secret"]):
                    key_col = c
                    break

        quota_col = args.quota_col
        if not quota_col:
            for c in fieldnames:
                if any(k in c.lower() for k in ["quota", "limit"]):
                    quota_col = c
                    break

        if not name_col:
            print(f"[-] Could not detect team name/id column from headers: {fieldnames}")
            print("    Please specify with --name-col <column_name>")
            return

        print(f"[*] Detected Columns -> Team: '{name_col}', Key: '{key_col}', Quota: '{quota_col}'")

        items = []
        for row in reader:
            t_name = str(row.get(name_col, "")).strip()
            if not t_name:
                continue
            t_key = str(row.get(key_col, "")).strip() if key_col else None
            t_quota = None
            if quota_col and row.get(quota_col):
                try:
                    t_quota = int(row.get(quota_col))
                except Exception:
                    pass

            items.append({
                "name": t_name,
                "token": t_key if t_key else None,
                "test_quota_limit": t_quota
            })

    if not items:
        print("[-] No rows to import.")
        return

    print(f"[*] Sending {len(items)} records to server...")
    with get_client(args.url, args.admin_key) as client:
        resp = client.post("/api/v1/admin/teams/import", json={
            "teams": items,
            "default_quota": args.default_quota
        })
        if resp.status_code == 200:
            data = resp.json()
            print(f"[+] Successfully processed {data['total']} teams:")
            for t in data["teams"]:
                print(f"    - {t['name']:<25} [{t['action'].upper()}] | Token: {t['token_prefix']} | Quota: {t['quota']}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_batch_add(args):
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    if not names:
        print("[-] No valid team names provided.")
        return

    with get_client(args.url, args.admin_key) as client:
        payload = {"team_names": names}
        if args.quota is not None:
            payload["test_quota_limit"] = args.quota

        resp = client.post("/api/v1/admin/teams/batch", json=payload)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[+] Batch creation finished ({data['total']} processed):\n")
            tokens_output = []
            for t in data["teams"]:
                if t.get("status") == "created":
                    print(f"  - {t['name']:<20} | Quota: {t['test_quota_limit']} | Token: {t['token']}")
                    tokens_output.append(f"{t['name']},{t['token']},{t['test_quota_limit']}")
                else:
                    print(f"  - {t['name']:<20} | Skipped: {t.get('reason')}")

            if args.save_csv and tokens_output:
                csv_path = Path(args.save_csv)
                with open(csv_path, "w", encoding="utf-8") as f:
                    f.write("team_name,token,quota\n" + "\n".join(tokens_output) + "\n")
                print(f"\n[+] Saved tokens CSV to: {csv_path.resolve()}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_list_teams(args):
    with get_client(args.url, args.admin_key) as client:
        resp = client.get("/api/v1/admin/teams")
        if resp.status_code == 200:
            teams = resp.json()
            print(f"\nRegistered Teams ({len(teams)}):\n")
            print(f"{'Team ID':<38} {'Name':<22} {'Quota':<7} {'Active':<8} {'Token Prefix'}")
            print("-" * 90)
            for t in teams:
                print(f"{t['id']:<38} {t['name']:<22} {t['test_quota_limit']:<7} {str(t['is_active']):<8} {t['token_prefix']}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_set_quota(args):
    with get_client(args.url, args.admin_key) as client:
        resp = client.post(f"/api/v1/admin/teams/{args.team_id}/quota", json={"test_quota_limit": args.quota})
        if resp.status_code == 200:
            print(f"[+] Quota updated: Team {args.team_id} new test limit is {args.quota}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_delete_team(args):
    with get_client(args.url, args.admin_key) as client:
        resp = client.delete(f"/api/v1/admin/teams/{args.team_id}")
        if resp.status_code == 200:
            print(f"[+] {resp.json().get('message')}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_stats(args):
    with get_client(args.url, args.admin_key) as client:
        resp = client.get("/api/v1/admin/stats")
        if resp.status_code == 200:
            stats = resp.json()
            print(f"\n{'Team Name':<22} {'Train (Req/Sub)':<18} {'Test (Req/Sub)':<16} {'Test Rem':<10} {'Avg Dur (s)'}")
            print("=" * 78)
            for s in stats:
                train_info = f"{s['train_dispatches']} / {s['train_submissions']}"
                test_info = f"{s['test_dispatches']} / {s['test_submissions']}"
                avg_str = f"{s['avg_duration_sec']}s" if s['avg_duration_sec'] is not None else "-"
                print(f"{s['team_name']:<22} {train_info:<18} {test_info:<16} {s['test_remaining']:<10} {avg_str}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def cmd_export(args):
    with get_client(args.url, args.admin_key) as client:
        print("[*] Requesting export zip...")
        resp = client.get("/api/v1/admin/export")
        if resp.status_code == 200:
            out_file = Path(args.output)
            out_file.write_bytes(resp.content)
            print(f"[+] Successfully exported submissions ({len(resp.content):,} bytes) to: {out_file.resolve()}")
        else:
            print(f"[-] Error: HTTP {resp.status_code} - {resp.text}")


def main():
    parser = argparse.ArgumentParser(description="TopGun Admin Command-Line Interface")
    parser.add_argument("--url", default=DEFAULT_URL, help="Base server URL")
    parser.add_argument("--admin-key", default=DEFAULT_ADMIN_KEY, help="Admin API Key")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # get-mode
    subparsers.add_parser("get-mode", help="Get current competition mode")

    # set-mode
    p_set_mode = subparsers.add_parser("set-mode", help="Set competition mode")
    p_set_mode.add_argument("mode", choices=["train", "test", "all", "paused"], help="Target mode")

    # add-team
    p_add_team = subparsers.add_parser("add-team", help="Add a single team")
    p_add_team.add_argument("name", help="Team name")
    p_add_team.add_argument("--token", help="Optional pre-generated key/token")
    p_add_team.add_argument("--quota", type=int, default=5, help="Test mode quota limit (default 5)")

    # edit-team
    p_edit_team = subparsers.add_parser("edit-team", help="Edit a team (name, token, quota, status)")
    p_edit_team.add_argument("team_id", help="Team UUID")
    p_edit_team.add_argument("--name", help="New team name")
    p_edit_team.add_argument("--token", help="Assign new custom secret token")
    p_edit_team.add_argument("--quota", type=int, help="New quota limit")
    p_edit_team.add_argument("--active", action="store_true", default=None, help="Set active")
    p_edit_team.add_argument("--inactive", dest="active", action="store_false", help="Set inactive")

    # import-csv
    p_import = subparsers.add_parser("import-csv", help="Import pre-generated keys from a CSV/TSV file")
    p_import.add_argument("file", help="Path to CSV/TSV file")
    p_import.add_argument("--name-col", help="Header name for team column (auto-detected if omitted)")
    p_import.add_argument("--key-col", help="Header name for key column (auto-detected if omitted)")
    p_import.add_argument("--quota-col", help="Header name for quota column (auto-detected if omitted)")
    p_import.add_argument("--default-quota", type=int, default=5, help="Default quota if missing (default 5)")

    # batch-add
    p_batch_add = subparsers.add_parser("batch-add", help="Add multiple teams (comma separated)")
    p_batch_add.add_argument("names", help="Comma-separated list of team names")
    p_batch_add.add_argument("--quota", type=int, default=5, help="Test mode quota limit")
    p_batch_add.add_argument("--save-csv", default="team_keys.csv", help="Filename to save generated keys")

    # list-teams
    subparsers.add_parser("list-teams", help="List all registered teams")

    # set-quota
    p_set_quota = subparsers.add_parser("set-quota", help="Change test quota for a team")
    p_set_quota.add_argument("team_id", help="Team ID")
    p_set_quota.add_argument("quota", type=int, help="New quota limit")

    # delete-team
    p_del_team = subparsers.add_parser("delete-team", help="Delete a team")
    p_del_team.add_argument("team_id", help="Team ID")

    # stats
    subparsers.add_parser("stats", help="Show overview stats for all teams")

    # export-data
    p_export = subparsers.add_parser("export-data", help="Download all JSON submissions as a zip")
    p_export.add_argument("--output", default="topgun_export.zip", help="Output file path")

    args = parser.parse_args()

    commands = {
        "get-mode": cmd_get_mode,
        "set-mode": cmd_set_mode,
        "add-team": cmd_add_team,
        "edit-team": cmd_edit_team,
        "import-csv": cmd_import_csv,
        "batch-add": cmd_batch_add,
        "list-teams": cmd_list_teams,
        "set-quota": cmd_set_quota,
        "delete-team": cmd_delete_team,
        "stats": cmd_stats,
        "export-data": cmd_export,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
