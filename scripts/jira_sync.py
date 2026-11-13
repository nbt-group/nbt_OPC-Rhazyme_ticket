"""
Jira -> Supabase sync (config driven, batched, incremental).

Usage (locally or in GitHub Actions):
    python scripts/jira_sync.py                 # incremental: tickets updated in the last 3 days
    FULL_SYNC=1 python scripts/jira_sync.py     # full re-sync of every ticket
    python scripts/jira_sync.py --list-fields   # print Jira field names + ids (to find customfield_xxxxx)
    python scripts/jira_sync.py emulsion        # sync only one target

Required env vars: JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN, SUPABASE_URL, SUPABASE_KEY
SUPABASE_KEY must be the *service_role* key (server side only, never put it in index.html).
"""
import os
import sys
import requests
from requests.auth import HTTPBasicAuth
from supabase import create_client

JIRA_DOMAIN = os.environ["JIRA_DOMAIN"]
AUTH = HTTPBasicAuth(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
FULL_SYNC = os.getenv("FULL_SYNC") == "1"
INCREMENTAL_WINDOW = os.getenv("SYNC_WINDOW", "-3d")
BATCH_SIZE = 200

# ---------------------------------------------------------------------------
# Column spec: supabase_column -> (jira_field_id, kind)
# kinds: str | int | float | option | user | name | comment | date
# ---------------------------------------------------------------------------
TARGETS = {
    "emulsion": {
        "table": "emulsion_tickets",
        "jql": 'project = "NBT Emulsions"',
        "columns": {
            "summary": ("summary", "str"),
            "assignee": ("assignee", "user"),
            "status": ("status", "name"),
            "customer": ("customfield_10213", "str"),
            "destination": ("customfield_10201", "str"),
            "item_1": ("customfield_10215", "option"),
            "qty_1": ("customfield_10216", "int"),
            "item_2": ("customfield_10217", "option"),
            "qty_2": ("customfield_10219", "int"),
            "item_3": ("customfield_10220", "option"),
            "qty_3": ("customfield_10218", "int"),
            "po_link": ("customfield_10245", "str"),
            "do_link": ("customfield_10235", "str"),
            "invoice_link": ("customfield_10236", "str"),
            "bc_bl_link": ("customfield_10242", "str"),
            "latest_comment": ("comment", "comment"),
            "updated_at": ("updated", "date"),
        },
    },
    "opc_rhazyme": {
        "table": "opc_rhazyme_tickets",
        "jql": "project = NOR",
        "columns": {
            "summary": ("summary", "str"),
            "assignee": ("assignee", "user"),
            "status": ("status", "name"),
            "customer": ("customfield_10282", "str"),
            "destination": ("customfield_10283", "option"),
            "site_location": ("customfield_10284", "str"),
            "site_pic": ("customfield_10285", "str"),
            "site_pic_contact": ("customfield_10286", "str"),
            "item_1": ("customfield_10287", "option"),
            "qty_1": ("customfield_10288", "int"),
            "item_2": ("customfield_10289", "option"),
            "qty_2": ("customfield_10290", "int"),
            "item_3": ("customfield_10291", "option"),
            "qty_3": ("customfield_10292", "int"),
            "budget": ("customfield_10279", "float"),
            "po_number": ("customfield_10280", "str"),
            "po_link": ("customfield_10281", "str"),
            "do_number": ("customfield_10293", "str"),
            "do_link": ("customfield_10294", "str"),
            "invoice_number": ("customfield_10295", "str"),
            "invoice_link": ("customfield_10296", "str"),
            "transport_company": ("customfield_10297", "str"),
            "transporter_contact": ("customfield_10298", "str"),
            "lorry_plate": ("customfield_10299", "str"),
            "vessel_booking_ref": ("customfield_10336", "str"),
            "bc_link": ("customfield_10337", "str"),
            "bl_link": ("customfield_10345", "str"),
            "pol": ("customfield_10341", "str"),
            "pod": ("customfield_10343", "str"),
            "pol_eta": ("customfield_10342", "date"),
            "pod_eta": ("customfield_10344", "date"),
            "port_cargo_ready_date": ("customfield_10338", "date"),
            "num_containers": ("customfield_10340", "int"),
            "production_etc": ("customfield_10334", "date"),
            "production_due_date": ("customfield_10339", "date"),
            "latest_comment": ("comment", "comment"),
            "created_at": ("created", "date"),
        },
    },
}


def extract(fields, field_id, kind):
    v = fields.get(field_id)
    if kind == "str":
        return v if isinstance(v, str) else (v.get("value", "") if isinstance(v, dict) else "")
    if kind == "int":
        try:
            return int(float(v or 0))
        except (TypeError, ValueError):
            return 0
    if kind == "float":
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    if kind == "option":
        return v.get("value", "") if isinstance(v, dict) else (v or "")
    if kind == "user":
        return v.get("displayName", "Unassigned") if isinstance(v, dict) else "Unassigned"
    if kind == "name":
        return v.get("name", "") if isinstance(v, dict) else ""
    if kind == "comment":
        comments = (v or {}).get("comments", []) if isinstance(v, dict) else []
        if not comments:
            return ""
        body = comments[-1].get("body", "")
        return body if isinstance(body, str) else ""
    if kind == "date":
        return v
    return v


def fetch_issues(jql, field_ids):
    """Yield issues page by page using Jira's token based pagination."""
    url = f"https://{JIRA_DOMAIN}/rest/api/2/search/jql"
    token = None
    while True:
        payload = {"jql": jql, "fields": sorted(field_ids), "maxResults": 100}
        if token:
            payload["nextPageToken"] = token
        r = requests.post(url, json=payload, auth=AUTH, timeout=60,
                          headers={"Accept": "application/json"})
        if not r.ok:
            raise RuntimeError(f"Jira error {r.status_code}: {r.text[:500]}")
        data = r.json()
        yield from data.get("issues", [])
        token = data.get("nextPageToken")
        if not token:
            return


def sync_target(supabase, name):
    cfg = TARGETS[name]
    cols = cfg["columns"]
    jql = cfg["jql"]
    if not FULL_SYNC:
        jql = f'({jql}) AND updated >= "{INCREMENTAL_WINDOW}"'
    jql += " ORDER BY updated DESC"

    needed = {fid for fid, _ in cols.values()}
    print(f"[{name}] {'FULL' if FULL_SYNC else 'INCREMENTAL'} sync -> {cfg['table']}\n  JQL: {jql}")

    rows, total = {}, 0

    def flush():
        nonlocal rows, total
        if rows:
            supabase.table(cfg["table"]).upsert(list(rows.values()), on_conflict="issue_key").execute()
            total += len(rows)
            print(f"  upserted {total} so far")
            rows = {}

    for issue in fetch_issues(jql, needed):
        fields = issue.get("fields", {})
        row = {"issue_key": issue["key"]}
        for col, (fid, kind) in cols.items():
            row[col] = extract(fields, fid, kind)
        rows[row["issue_key"]] = row  # dict dedupes keys inside one batch
        if len(rows) >= BATCH_SIZE:
            flush()
    flush()
    print(f"[{name}] done, {total} tickets synced")


def list_fields():
    r = requests.get(f"https://{JIRA_DOMAIN}/rest/api/2/field", auth=AUTH, timeout=60)
    r.raise_for_status()
    for f in sorted(r.json(), key=lambda x: x["id"]):
        if f["id"].startswith("customfield_"):
            print(f"{f['id']:<22} {f['name']}")


if __name__ == "__main__":
    if "--list-fields" in sys.argv:
        list_fields()
        sys.exit(0)
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")] or list(TARGETS)
    failed = []
    for t in wanted:
        try:
            sync_target(sb, t)
        except Exception as e:  # keep going so one broken target doesn't block the others
            print(f"[{t}] FAILED: {e}")
            failed.append(t)
    sys.exit(1 if failed else 0)
