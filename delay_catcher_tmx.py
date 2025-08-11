# delay_catcher_tmx.py — main process

# Purpose: Track and analyze delay changes in Asana tasks:
# - If due_on is pushed later or removed (parked) → increment "Delay Count"
# - If "Delay Reason" changes → log to Google Sheet
# - If a delay occurs without a reason → auto-set "Awaiting identify"

# Notes:
# - Uses Asana REST API (no pagination implemented yet)
# - Persists state in SQLite; WAL mode enabled for better concurrency
# - Google Sheet logging is best-effort (no retry/backoff)


from dotenv import load_dotenv
import os

load_dotenv()

import argparse
import sqlite3
import requests
import json
from datetime import datetime
from typing import List, Dict, Optional
from datetime import timezone

DB_PATH = "asana_tasks.db"
BASE_URL = "https://app.asana.com/api/1.0"

class AsanaManager:
    def __init__(self, token: str, workspace_id: str):
        """
        Initialize API headers and DB schema.

        token: Personal access token for Asana API.
        workspace_id: Not strictly used in this module but kept for parity with future use.

        - All network calls are synchronous and may raise requests exceptions in extreme cases.
        - We intentionally keep error handling light; systemd is expected to restart the process on fatal errors.
        """
                
        self.token = token
        self.workspace_id = workspace_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.init_database()

    def init_database(self):
        """
        Create core tables if missing.

        Tables:
        - tasks: last known snapshot of each task (including custom_fields JSON)
        - due_date_updates: normalized history of due date changes
        - delay_reason_updates: normalized history of delay reason changes

        Notes:
        - We leave existing unused tables (if any) untouched; safe to DROP offline if desired.
        - A defensive ALTER is issued to ensure `is_delay` exists in due_date_updates.
        """

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # cursor.execute('''
        #     CREATE TABLE IF NOT EXISTS projects (
        #         gid TEXT PRIMARY KEY,
        #         name TEXT,
        #         team TEXT,
        #         created_at TEXT,
        #         modified_at TEXT,
        #         last_updated TEXT
        #     )
        # ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                gid TEXT PRIMARY KEY,
                name TEXT,
                project_gid TEXT,
                assignee_name TEXT,
                completed BOOLEAN,
                completed_at TEXT,
                created_at TEXT,
                modified_at TEXT,
                due_on TEXT,
                notes TEXT,
                permalink_url TEXT,
                custom_fields TEXT,
                last_updated TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS due_date_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_gid TEXT,
                old_due_on TEXT,
                new_due_on TEXT,
                update_date TEXT,
                is_delay INTEGER DEFAULT 0,
                FOREIGN KEY(task_gid) REFERENCES tasks(gid)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS delay_reason_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_gid TEXT,
                old_reason TEXT,
                new_reason TEXT,
                update_date TEXT,
                changed_by TEXT,
                FOREIGN KEY(task_gid) REFERENCES tasks(gid)
            )
        ''')

        # Ensure is_delay column exists (to avoid missing it when the DB is first created).
        # On fresh DBs, the CREATE TABLE above already defines it; the ALTER will raise and be ignored.
        try:
            cursor.execute("ALTER TABLE due_date_updates ADD COLUMN is_delay INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()

    # def get_saved_projects(self) -> List[Dict]:
    #     conn = sqlite3.connect(DB_PATH)
    #     cursor = conn.cursor()
    #     cursor.execute('SELECT gid, name, team FROM projects ORDER BY name')
    #     projects = [
    #         {'gid': row[0], 'name': row[1], 'team': row[2]}
    #         for row in cursor.fetchall()
    #     ]
    #     conn.close()
    #     return projects

    def get_project_tasks(self, project_gid: str) -> List[Dict]:
        """
        Fetch tasks for a project with selected fields.
        - This fetches a single page only (no pagination). If your project exceeds the default page size,
          you may miss tasks. Consider implementing offset-based pagination if needed.
        - Request `custom_fields` on tasks so downstream functions can compute delay count/reason.
        """

        params = {
            "opt_fields": "gid,name,assignee.name,completed,completed_at,created_at,modified_at,due_on,notes,permalink_url,custom_fields"
        }
        response = requests.get(f"{BASE_URL}/projects/{project_gid}/tasks", headers=self.headers, params=params)
        if response.status_code == 200:
            return response.json()['data']
        else:
            print(f"Failed to fetch tasks. Status code: {response.status_code}")
            return []

    def get_task_stories(self, task_gid: str) -> List[Dict]:
        """
        Fetch stories (activity log) for a task.
        Rely on:
        - resource_subtype == 'due_date_changed' for due_on changes
        - resource_subtype == 'enum_custom_field_changed' for delay reason updates

        The most recent relevant story is used as the authoritative "who/when" metadata
        for spreadsheet logging. If none is found, fall back to task.modified_at/modified_by.
        """

        params = {
            "opt_fields": "resource_subtype,custom_field.name,old_enum_value.name,new_enum_value.name,created_at,created_by.name"
        }
        response = requests.get(f"{BASE_URL}/tasks/{task_gid}/stories", headers=self.headers, params=params)
        if response.status_code == 200:
            return response.json()['data']
        else:
            print(f"Failed to fetch stories for task {task_gid}")
            return []

    def update_project_data(self, project_gid: str):
        """
        Pull the latest tasks → detect and persist changes → log to Google Sheet (best-effort).
        This is the main entry point invoked by `main()`.
        """
        tasks = self.get_project_tasks(project_gid)
        self.save_tasks_to_db(tasks, project_gid)

    def is_due_date_delayed(self, old: Optional[str], new: Optional[str]) -> bool:
        """
        Decide if a change constitutes a delay.

        Rules:
        - old set, new None  → treated as parked → delay
        - old set, new set   → delay if new > old
        - other cases        → not a delay

        Format assumption:
        - Compare ISO dates from Asana `due_on` (YYYY-MM-DD). If you switch to `due_at` (with time/UTC),
          adjust parsing accordingly (e.g., handle 'Z' and timezone offsets).
        """
        if old and not new:
            return True  # due date removed = parked --> delay
        if old and new:
            try:
                old_dt = datetime.fromisoformat(old)
                new_dt = datetime.fromisoformat(new)
                return new_dt > old_dt
            except Exception:
                return False
        return False

    # Custom field helpers -- for extract_delay_count_field_gid, get_current_delay_count, get_current_delay_reason, has_delay_reason
        # Identify fields by their display names using case-insensitive contains:
        #   - "Delay Count" (number)
        #   - "Delay Reason" (enum)
        # Ensure the Asana custom field names match these substrings.

    def extract_delay_count_field_gid(self, custom_fields: List[Dict]) -> Optional[str]:
        for field in custom_fields:
            if 'delay count' in field.get('name', '').lower():
                return field.get('gid')
        return None

    def get_current_delay_count(self, custom_fields: List[Dict]) -> int:
        for field in custom_fields:
            if 'delay count' in field.get('name', '').lower():
                return int(field.get('number_value') or 0)
        return 0

    def get_current_delay_reason(self, custom_fields: List[Dict]) -> Optional[str]:
        for field in custom_fields:
            if 'delay reason' in field.get('name', '').lower():
                enum_val = field.get('enum_value')
                return enum_val.get('name') if enum_val else None
        return None

    def has_delay_reason(self, custom_fields: List[Dict]) -> bool:
        for field in custom_fields:
            if 'delay reason' in field.get('name', '').lower():
                return field.get('enum_value') is not None
        return False
    
    def set_delay_reason_awaiting(self, task_gid: str, custom_fields: List[Dict]):
        """
        Auto-set "Delay Reason" to 'Awaiting identify' when a delay is detected without a reason.

        Implementation details:
        - If enum options are not present on the task payload, fetch the custom field definition.
        - Compare options by case-insensitive exact name match ('awaiting identify').
        - This may fail if the user lacks permission to update the custom field or if the field is not
          attached to the project—errors are logged but not retried.
        """

        for field in custom_fields:
            if 'delay reason' in field.get('name', '').lower():
                field_gid = field['gid']
                enum_options = field.get('enum_options', [])

                if not enum_options:
                    # If options are not included in the task API response, re-fetch the field information.
                    field_resp = requests.get(f"{BASE_URL}/custom_fields/{field_gid}", headers=self.headers)
                    if field_resp.status_code == 200:
                        enum_options = field_resp.json().get('data', {}).get('enum_options', [])
                    else:
                        print(f"❌ Failed to fetch enum options for delay reason (field_gid={field_gid})")
                        return

                for option in enum_options:
                    if option['name'].strip().lower() == 'awaiting identify':
                        awaiting_gid = option['gid']
                        payload = {
                            "data": {
                                "custom_fields": {
                                    field_gid: awaiting_gid
                                }
                            }
                        }
                        response = requests.put(f"{BASE_URL}/tasks/{task_gid}", headers=self.headers, json=payload)
                        if response.status_code == 200:
                            print(f"🟡 Set delay reason to 'Awaiting identify' for task {task_gid}")
                        else:
                            print(f"❌ Failed to set delay reason for task {task_gid}: {response.status_code}")
                        return

    def get_task_by_gid(self, task_gid: str) -> Optional[Dict]:
        """
        Re-fetch a task to obtain the latest custom_fields after updating Asana (e.g., after incrementing Delay Count).
        This helps ensure we log consistent, current values to the Google Sheet.
        """

        response = requests.get(f"{BASE_URL}/tasks/{task_gid}?opt_fields=custom_fields", headers=self.headers)
        if response.status_code == 200:
            return response.json().get('data')
        else:
            print(f"❌ Failed to fetch task {task_gid} for updated fields.")
            return None

    def increment_delay_count(self, task_gid: str, custom_fields: List[Dict]):
        """
        Increment the numeric 'Delay Count' custom field by 1.

        Notes:
        - Compute the new value from the caller-provided `custom_fields` snapshot,
          then update the task. The final value is confirmed later in `_log_to_spreadsheet`
          via a fresh `get_task_by_gid` call.
        - If the task has no 'Delay Reason', we call `set_delay_reason_awaiting`.
        - No retry/backoff on non-200 responses; errors are logged.
        """

        field_gid = self.extract_delay_count_field_gid(custom_fields)
        if not field_gid:
            print(f"No Delay Count field found in task {task_gid}")
            return

        current_value = self.get_current_delay_count(custom_fields)
        payload = {
            "data": {
                "custom_fields": {
                    field_gid: current_value + 1
                }
            }
        }
        response = requests.put(f"{BASE_URL}/tasks/{task_gid}", headers=self.headers, json=payload)
        if response.status_code != 200:
            print(f"❌ Failed to update delay count for {task_gid}. Status: {response.status_code}")
        else:
            print(f"✅ Delay Count incremented for task {task_gid}")

        # If delay reason is not provided, automatically fill in "Awaiting identify".
        if not self.has_delay_reason(custom_fields):
            self.set_delay_reason_awaiting(task_gid, custom_fields)

    def post_to_sheet(self, payload: Dict):
        """
        Best-effort logging to a Google Apps Script webhook.

        Environment:
        - Requires SHEET_WEBHOOK_URL in the environment.
        Behavior:
        - 5s timeout; no retries or backoff.
        - Exceptions are caught and printed; they do not stop the main flow.
        """

        SHEET_WEBHOOK = os.getenv("SHEET_WEBHOOK_URL")
        try:
            requests.post(SHEET_WEBHOOK, json=payload, timeout=5)
        except Exception as e:
            print("Sheet webhook error:", e)

    def save_tasks_to_db(self, tasks: List[Dict], project_gid: str):
        """
        Persist the latest snapshot of tasks and detect changes.

        Workflow per task:
        1) Read prior snapshot (due_on + custom_fields JSON) from `tasks`
        2) Determine:
           - due_date_changed (and whether it's a "delay")
           - delay_reason_changed (enum value actually changed)
        3) If any change:
           - Write to due_date_updates / delay_reason_updates, with dedup checks
           - Increment delay count (only for delays)
           - Log a single merged entry to the spreadsheet (change_type can be 'due_date_change',
             'delay_reason_change', or 'due_date_change+delay_reason_change')
        4) Upsert the `tasks` snapshot

        Notes:
        - Dedup is by (task_gid, old_due_on, new_due_on) or (task_gid, old_reason, new_reason)
        - Store custom_fields as JSON to compare historical reasons and avoid extra API calls
        - DB is set to WAL mode to reduce writer contention; still assume single-process execution
        """

        conn = sqlite3.connect(DB_PATH)
        conn.execute('PRAGMA journal_mode=WAL')
        cursor = conn.cursor()

        for task in tasks:
            task_gid = str(task['gid'])  # Ensure task_gid is in string format
            assignee = task.get('assignee')
            assignee_name = assignee['name'] if assignee and 'name' in assignee else 'Unassigned'
            new_due_on = task.get('due_on', '')
            custom_fields = task.get('custom_fields', [])
            custom_fields_json = json.dumps(custom_fields)
            
            # Get the current delay reason
            current_delay_reason = self.get_current_delay_reason(custom_fields)

            # Check old data
            cursor.execute('SELECT due_on, custom_fields FROM tasks WHERE gid = ?', (task_gid,))
            existing = cursor.fetchone()
            old_due_on = existing[0] if existing else ''
            old_custom_fields_json = existing[1] if existing else ''
            
            # Parse the old delay reason
            old_delay_reason = ""
            if old_custom_fields_json:
                try:
                    old_custom_fields = json.loads(old_custom_fields_json)
                    old_delay_reason = self.get_current_delay_reason(old_custom_fields) or ""
                except:
                    old_delay_reason = ""

            # Mark whether there is a change
            due_date_changed = old_due_on != new_due_on and self.is_due_date_delayed(old_due_on, new_due_on)
            delay_reason_changed = old_delay_reason != (current_delay_reason or "") and current_delay_reason
            # `delay_reason_changed` will be either False or a truthy string (the new reason).
            # Rely on Python truthiness for the subsequent if; this improves readability of the condition.
            
            # Handle changes (merge logic) - Handle changes together so we can log one combined spreadsheet row when both happened simultaneously.
            if due_date_changed or delay_reason_changed:
                self._handle_combined_changes(cursor, task, task_gid, old_due_on, new_due_on, 
                                            old_delay_reason, current_delay_reason, assignee_name, 
                                            custom_fields, due_date_changed, delay_reason_changed)

            # Update or insert task data 
            cursor.execute('''
                INSERT OR REPLACE INTO tasks 
                (gid, name, project_gid, assignee_name, completed, completed_at, created_at, 
                modified_at, due_on, notes, permalink_url, custom_fields, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_gid,
                task['name'],
                project_gid,
                assignee_name,
                task.get('completed', False),
                task.get('completed_at', ''),
                task.get('created_at', ''),
                task.get('modified_at', ''),
                new_due_on,
                task.get('notes', ''),
                task.get('permalink_url', ''),
                custom_fields_json,
                datetime.now().isoformat()
            ))

        conn.commit()
        conn.close()

    def _handle_combined_changes(self, cursor, task: Dict, task_gid: str, old_due_on: str, new_due_on: str, 
                               old_delay_reason: str, new_delay_reason: str, assignee_name: str, 
                               custom_fields: List[Dict], due_date_changed: bool, delay_reason_changed: bool):
        """
        Insert change records with dedup and orchestrate side effects.

        - Due date changes:
          * Insert into due_date_updates with is_delay=1 only when new > old (or when removed)
          * Increment the task's Delay Count custom field
        - Delay reason changes:
          * Insert into delay_reason_updates with who/when from stories (fallback to task metadata)
        - Spreadsheet:
          * Emit a single merged row to avoid double-logging if both changed at once

        Caveat:
        - "who/when" is derived from the latest relevant story; if none is found, fall back to task.modified_at/modified_by.
          That fallback may not precisely represent the specific field change.
        """
        
        change_types = []
        
        # 1. Handle due date changes
        if due_date_changed:
            # Avoid recording the same due_on change repeatedly.
            cursor.execute('''
                SELECT COUNT(*) FROM due_date_updates
                WHERE task_gid = ? AND old_due_on = ? AND new_due_on = ?
            ''', (task_gid, old_due_on, new_due_on))
            already_logged = cursor.fetchone()[0]

            if not already_logged:
                print(f"🔄 Due date delayed for task {task['name']}: {old_due_on} → {new_due_on}")
                
                modifier_info = self._get_latest_due_date_modifier(task_gid)
                cursor.execute('''
                    INSERT INTO due_date_updates (task_gid, old_due_on, new_due_on, update_date, is_delay)
                    VALUES (?, ?, ?, ?, ?)
                ''', (task_gid, old_due_on, new_due_on, modifier_info['updated_at'], 1))

                self.increment_delay_count(task_gid, custom_fields)
                change_types.append("due_date_change")

        # 2. Handle delay reason changes
        if delay_reason_changed:
            # Avoid recording the same change repeatedly
            cursor.execute('''
                SELECT COUNT(*) FROM delay_reason_updates
                WHERE task_gid = ? AND old_reason = ? AND new_reason = ?
            ''', (task_gid, old_delay_reason, new_delay_reason))
            already_logged = cursor.fetchone()[0]

            if not already_logged:
                print(f"🔄 Delay reason changed for task {task['name']}: '{old_delay_reason}' → '{new_delay_reason}'")
                
                modifier_info = self._get_latest_delay_reason_modifier(task_gid, new_delay_reason)
                cursor.execute('''
                    INSERT INTO delay_reason_updates 
                    (task_gid, old_reason, new_reason, update_date, changed_by)
                    VALUES (?, ?, ?, ?, ?)
                ''', (task_gid, old_delay_reason, new_delay_reason, modifier_info['updated_at'], modifier_info['updated_by']))

                change_types.append("delay_reason_change")

        # 3. Log to Spreadsheet (merge into a single entry) 
        if change_types:
            # Prefer using the modifier_info from delay reason; if not available, use that from due date.
            if delay_reason_changed:
                modifier_info = self._get_latest_delay_reason_modifier(task_gid, new_delay_reason)
            else:
                modifier_info = self._get_latest_due_date_modifier(task_gid)
            
            combined_change_type = "+".join(change_types)
            self._log_to_spreadsheet(cursor, task, task_gid, modifier_info, combined_change_type)

    def _log_to_spreadsheet(self, cursor, task: Dict, task_gid: str, modifier_info: Dict, change_type: str):
        """
        Build a normalized record and send to the Google Sheet webhook.

        - task_gid is prefixed with "'" to avoid scientific notation in Excel/Sheets exports
        - first_due_on is computed from the earliest recorded old_due_on for this task
        - latest_due_on comes from the current task snapshot
        - delay_duration = (latest_due_on - first_due_on) in days, or '' if either date is missing
          (parked tasks produce '' because latest_due_on is empty)

        change_type examples:
        - 'due_date_change'
        - 'delay_reason_change'
        - 'due_date_change+delay_reason_change'
        """
        
        # Fetch the latest task data (including the updated delay count, etc.)
        updated_task = self.get_task_by_gid(task_gid)
        if not updated_task:
            print(f"❌ Failed to get updated task data for {task_gid}")
            return

        updated_fields = updated_task.get('custom_fields', [])
        delay_count = self.get_current_delay_count(updated_fields)
        current_delay_reason = self.get_current_delay_reason(updated_fields) or "Awaiting identify"
        
        # Get the earliest due date
        cursor.execute('SELECT MIN(old_due_on) FROM due_date_updates WHERE task_gid = ?', (task_gid,))
        first_due_result = cursor.fetchone()
        first_due_on = first_due_result[0] if first_due_result and first_due_result[0] else ''
        
        latest_due_on = task.get('due_on', '')
        
        # Calculate the delay duration
        delay_duration = ''
        if first_due_on and latest_due_on:
            try:
                d1 = datetime.fromisoformat(first_due_on)
                d2 = datetime.fromisoformat(latest_due_on)
                delay_duration = (d2 - d1).days
            except Exception as e:
                print(f"⚠️ Error calculating delay duration: {e}")

        # Ensure all data formats are correct and fix the Excel scientific notation issue
        payload = {
            "task_gid": f"'{task_gid}",  # Prefix with a single quote to force Excel to treat it as text
            "task_name": str(task['name']),
            "delay_count": int(delay_count),  # Ensure it is an integer
            "new_reason": str(current_delay_reason),
            "first_due_on": str(first_due_on),
            "latest_due_on": str(latest_due_on),
            "delay_duration": int(delay_duration) if delay_duration != '' else '', # Ensure it is an integer or an empty string
            "updated_at": str(modifier_info['updated_at']),
            "updated_by": str(modifier_info['updated_by']),
            "change_type": str(change_type)
        }
        
        self.post_to_sheet(payload)
        print(f"📊 Logged to spreadsheet: {task['name']} ({change_type})")

    def _get_latest_due_date_modifier(self, task_gid: str) -> Dict[str, str]:
        """
        Return {'updated_at': ISO8601, 'updated_by': str} for the most recent due date change.

        Strategy:
        - Scan stories sorted by created_at desc; use the first with resource_subtype='due_date_changed'
        - Fallback to task.modified_at/modified_by if no story exists
        - Timestamps are left as-is (Asana returns UTC with 'Z'); local isoformat() is used for fallbacks
        """

        stories = self.get_task_stories(task_gid)
        
        # Find the latest due date change
        for story in sorted(stories, key=lambda x: x.get('created_at', ''), reverse=True):
            if story.get('resource_subtype') == 'due_date_changed':
                created_by = story.get('created_by', {})
                return {
                    'updated_at': story.get('created_at', datetime.now().isoformat()),
                    'updated_by': created_by.get('name', 'Unknown') if created_by else 'Unknown'
                }
        
        # If no due date change record is found, try to get the modifier info from the task itself
        task_response = requests.get(f"{BASE_URL}/tasks/{task_gid}?opt_fields=modified_at,modified_by.name", headers=self.headers)
        if task_response.status_code == 200:
            task_data = task_response.json().get('data', {})
            modified_by = task_data.get('modified_by', {})
            return {
                'updated_at': task_data.get('modified_at', datetime.now().isoformat()),
                'updated_by': modified_by.get('name', 'Unknown') if modified_by else 'Unknown'
            }
        
        return {
            'updated_at': datetime.now().isoformat(),
            'updated_by': 'Unknown'
        }

    def _get_latest_delay_reason_modifier(self, task_gid: str, new_reason: str) -> Dict[str, str]:
        """
        Return {'updated_at': ISO8601, 'updated_by': str} for the most recent delay reason change
        that matches the provided new_reason.

        Strategy:
        - Scan stories (desc) with resource_subtype='enum_custom_field_changed' and custom_field name containing 'delay reason'
        - Only accept a story if new_enum_value.name == new_reason (guards against unrelated enum changes)
        - Fallback to task.modified_at/modified_by if no matching story exists
        """

        stories = self.get_task_stories(task_gid)
        
        # Find the latest delay reason change
        for story in sorted(stories, key=lambda x: x.get('created_at', ''), reverse=True):
            if (story.get('resource_subtype') == 'enum_custom_field_changed' and 
                story.get('custom_field', {}).get('name', '').lower().find('delay reason') != -1):
                
                new_enum = story.get('new_enum_value', {})
                if new_enum and new_enum.get('name') == new_reason:
                    created_by = story.get('created_by', {})
                    return {
                        'updated_at': story.get('created_at', datetime.now().isoformat()),
                        'updated_by': created_by.get('name', 'Unknown') if created_by else 'Unknown'
                    }
        
        # If no corresponding change record is found, try to get the modifier info from the task itself.
        task_response = requests.get(f"{BASE_URL}/tasks/{task_gid}?opt_fields=modified_at,modified_by.name", headers=self.headers)
        if task_response.status_code == 200:
            task_data = task_response.json().get('data', {})
            modified_by = task_data.get('modified_by', {})
            return {
                'updated_at': task_data.get('modified_at', datetime.now().isoformat()),
                'updated_by': modified_by.get('name', 'Unknown') if modified_by else 'Unknown'
            }
            
        return {
            'updated_at': datetime.now().isoformat(),
            'updated_by': 'Unknown'
        }

    # Currently not used, but kept for potential future reference
    # def get_delay_reason_changes(self, task_gid: str, task: Dict) -> List[Dict]:
    #     stories = self.get_task_stories(task_gid)
    #     changes = []

    #     # Get the last processed time for this task (for filtering)
    #     conn = sqlite3.connect(DB_PATH)
    #     cursor = conn.cursor()
    #     cursor.execute("SELECT last_updated FROM tasks WHERE gid = ?", (task_gid,))
    #     row = cursor.fetchone()
    #     last_updated = datetime.min
    #     if row and row[0]:
    #         try:
    #             last_updated = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
    #         except:
    #             pass
    #     conn.close()

    #     for s in stories:
    #         custom_field = s.get('custom_field')
    #         if not custom_field:
    #             continue

    #         field_name = custom_field.get('name', '').lower()
    #         created_at = s.get('created_at', '')
    #         try:
    #             created_at_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    #         except Exception:
    #             continue

    #         # Filter out changes that already existed before the last processing time.
    #         if created_at_dt <= last_updated:
    #             continue

    #         if s.get('resource_subtype') == 'enum_custom_field_changed' and 'delay reason' in field_name:
    #             old_enum = s.get('old_enum_value')
    #             new_enum = s.get('new_enum_value')
    #             old_r = old_enum.get('name', '') if old_enum else ''
    #             new_r = new_enum.get('name', '') if new_enum else ''

    #             if old_r != new_r:
    #                 changes.append({
    #                     'task_gid': f"'{task_gid}",  # Prefix with a single quote to fix Excel formatting issues.
    #                     'task_name': task['name'],
    #                     'old_reason': old_r,
    #                     'new_reason': new_r,
    #                     'update_date': created_at,
    #                     'changed_by': s.get('created_by', {}).get('name', '') if s.get('created_by') else ''
    #                 })

    #     return changes

    # def analyze_due_on_updates(self, project_gid: str):
    #     conn = sqlite3.connect(DB_PATH)
    #     cursor = conn.cursor()
    #     cursor.execute('''
    #         SELECT d.task_gid, t.name, t.assignee_name, d.old_due_on, d.new_due_on, d.update_date
    #         FROM due_date_updates d
    #         JOIN tasks t ON d.task_gid = t.gid
    #         WHERE t.project_gid = ? AND d.is_delay = 1
    #         ORDER BY d.update_date
    #     ''', (project_gid,))

    #     changes = cursor.fetchall()
    #     print("\n=== Due Date Delays Detected ===")
    #     for row in changes:
    #         print(f"- {row[1]} (Assignee: {row[2]})")
    #         print(f"  From: {row[3]} → To: {row[4]} at {row[5]}")
    #     print(f"\nTotal delayed tasks found: {len(changes)}")
    #     conn.close()

    # def analyze_delay_reason_updates(self, project_gid: str):
    #     conn = sqlite3.connect(DB_PATH)
    #     cur = conn.cursor()
    #     cur.execute('''
    #         SELECT t.name, d.old_reason, d.new_reason, d.update_date, d.changed_by
    #         FROM delay_reason_updates d
    #         JOIN tasks t ON d.task_gid = t.gid
    #         WHERE t.project_gid = ?
    #         ORDER BY d.update_date
    #     ''', (project_gid,))
    #     rows = cur.fetchall()
    #     print("\n=== Delay Reason Changes ===")
    #     for n, old, new, dt, by in rows:
    #         print(f"- {n}: '{old}' → '{new}' at {dt} by {by}")
    #     print(f"\nTotal reason updates: {len(rows)}")
    #     conn.close()

def main():
    """
    Entry point:
    - Reads ASANA_TOKEN, ASANA_WORKSPACE_ID, and ASANA_TMX_PROJECT_ID from environment (or CLI flags)
    - Performs one pass of update_project_data(project_gid)
    - Designed to be run by systemd on a schedule or kept alive by a wrapper service
    """

    parser = argparse.ArgumentParser(description="Delay Catcher – Track due_on changes")
    parser.add_argument("--asana-token", default=os.getenv("ASANA_TOKEN")) # Asana Token
    parser.add_argument("--workspace-id", default=os.getenv("ASANA_WORKSPACE_ID"))
    args = parser.parse_args()

    manager = AsanaManager(args.asana_token, args.workspace_id)

    print("=== Delay Catcher Dev Mode ===")
    
    # projects = manager.get_saved_projects()

    # for i, project in enumerate(projects):
    #     print(f"{i+1}. {project['name']} (Team: {project['team']})")

    # choice = int(input("Select a project: ")) - 1
    # project_gid = projects[choice]['gid']
    
    # Single-project mode:
    # Itentionally ignore any project list and rely on ASANA_TMX_PROJECT_ID for now.
    project_gid = os.getenv("ASANA_TMX_PROJECT_ID")

    print("\nAuto-running: Update Asana data...\n")
    manager.update_project_data(project_gid)

    # print("\nAuto-running: Analyze due date changes...\n")
    # manager.analyze_due_on_updates(project_gid)

    # print("\nAuto-running: Delay reason analysis...\n")
    # manager.analyze_delay_reason_updates(project_gid)

if __name__ == "__main__":
    main()

# Deployment note:
# - Ensure only one instance runs (systemd service with Restart=always; no duplicate processes)
# - Provide .env with ASANA_TOKEN / ASANA_TMX_PROJECT_ID / SHEET_WEBHOOK_URL
#    - If tracking another project: Change ASANA_TMX_PROJECT_ID to other project's gid and change all "tmx" mark
# - Logs are stdout; use `journalctl -u <service>` to follow

# NUC with systemd 250809 o/