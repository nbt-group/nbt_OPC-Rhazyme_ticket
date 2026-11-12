import os
import requests
from requests.auth import HTTPBasicAuth
from supabase import create_client, Client

JIRA_DOMAIN = os.getenv("JIRA_DOMAIN")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def sync_emulsion_tickets():
    url = f"https://{JIRA_DOMAIN}/rest/api/2/search/jql"
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # Pagination control variables
    next_page_token = None
    max_results = 100
    target_limit = 500
    total_synced = 0
    
    print(f"Connecting to Jira via POST: {url}")
    
    while total_synced < target_limit:
        # Remove 'startAt' - it is invalid on this endpoint
        payload = {
            "jql": 'project = "NBT Emulsions"', 
            "fields": ["*all"], 
            "maxResults": max_results
        }
        
        # Inject the token if we are fetching page 2 or beyond
        if next_page_token:
            payload["nextPageToken"] = next_page_token
            
        response = requests.post(url, headers=headers, json=payload, auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN))
        
        if not response.ok:
            print(f"Jira API Error {response.status_code}: {response.text}")
            break
            
        jira_data = response.json()
        issues = jira_data.get("issues", [])
        
        # Stop completely if 0 issues return on the very first try
        if len(issues) == 0:
            if total_synced == 0:
                print("Raw Jira Response:", jira_data)
            break

        for issue in issues:
            fields = issue.get("fields", {})
            key = issue["key"]
            
            comments_array = fields.get("comment", {}).get("comments", [])
            latest_comment = "<i>No comments yet.</i>"
            if comments_array:
                raw_comment = comments_array[-1].get("body", "<i>No comments yet.</i>")
                latest_comment = raw_comment.replace("\n", "<br>")

            def get_item_val(field_id):
                val = fields.get(field_id)
                return val.get("value", "") if isinstance(val, dict) else (val or "")

            data = {
                "issue_key": key,
                "summary": fields.get("summary", ""),
                "assignee": fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned",
                "status": fields.get("status", {}).get("name", ""),
                "customer": fields.get("customfield_10213", ""), 
                "destination": fields.get("customfield_10201", ""), 
                "item_1": get_item_val("customfield_10215"),
                "qty_1": int(fields.get("customfield_10216") or 0), 
                "item_2": get_item_val("customfield_10217"), 
                "qty_2": int(fields.get("customfield_10219") or 0),
                "item_3": get_item_val("customfield_10220"), 
                "qty_3": int(fields.get("customfield_10218") or 0),
                "po_link": fields.get("customfield_10245", ""), 
                "do_link": fields.get("customfield_10235", ""),
                "invoice_link": fields.get("customfield_10236", ""),
                "bc_bl_link": fields.get("customfield_10242", ""),
                "latest_comment": latest_comment,
                "updated_at": fields.get("updated")
            }
            
            supabase.table("emulsion_tickets").upsert(data).execute()
            print(f"Synced Ticket: {key}")
            total_synced += 1
            
            # Enforce the 500 ticket hard limit
            if total_synced >= target_limit:
                break

        # Advance the pagination cursor using Jira's new token system
        next_page_token = jira_data.get("nextPageToken")
        
        # Break the loop early if Jira does not return a token (meaning no more tickets exist)
        if not next_page_token:
            break

    print(f"Database sync complete. Total synced: {total_synced}")

if __name__ == "__main__":
    sync_emulsion_tickets()
