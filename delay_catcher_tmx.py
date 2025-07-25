# delay_catcher_dev.py
# 🧪 Experimental Asana Script – Due Date Change Tracker
# Author: Yu-Lin Kao
# Purpose: Track and analyze due_on changes in Asana tasks, increment Delay Count, and log Delay Reason changes

import argparse
import sqlite3
import requests
import json
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = "asana_tasks.db"
BASE_URL = "https://app.asana.com/api/1.0"

class AsanaManager:
    def __init__(self, token: str, workspace_id: str):
        self.token = token
        self.workspace_id = workspace_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.init_database()

    def init_database(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                gid TEXT PRIMARY KEY,
                name TEXT,
                team TEXT,
                created_at TEXT,
                modified_at TEXT,
                last_updated TEXT
            )
        ''')

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

        # ✅ 確保 is_delay 欄位存在（避免初次建立 DB 時缺少該欄位）
        try:
            cursor.execute("ALTER TABLE due_date_updates ADD COLUMN is_delay INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()

    def get_saved_projects(self) -> List[Dict]:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT gid, name, team FROM projects ORDER BY name')
        projects = [
            {'gid': row[0], 'name': row[1], 'team': row[2]}
            for row in cursor.fetchall()
        ]
        conn.close()
        return projects

    def get_project_tasks(self, project_gid: str) -> List[Dict]:
        params = {
            "project": project_gid,
            "opt_fields": "gid,name,assignee.name,completed,completed_at,created_at,modified_at,due_on,notes,permalink_url,custom_fields"
        }
        response = requests.get(f"{BASE_URL}/tasks", headers=self.headers, params=params)
        if response.status_code == 200:
            return response.json()['data']
        else:
            print(f"Failed to fetch tasks. Status code: {response.status_code}")
            return []

    def get_task_stories(self, task_gid: str) -> List[Dict]:
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
        tasks = self.get_project_tasks(project_gid)
        self.save_tasks_to_db(tasks, project_gid)

    def is_due_date_delayed(self, old: Optional[str], new: Optional[str]) -> bool:
        if old and not new:
            return True  # due date removed = parked
        if old and new:
            try:
                old_dt = datetime.fromisoformat(old)
                new_dt = datetime.fromisoformat(new)
                return new_dt > old_dt
            except Exception:
                return False
        return False

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

    def increment_delay_count(self, task_gid: str, custom_fields: List[Dict]):
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
            print(f"Failed to update delay count for {task_gid}. Status: {response.status_code}")

    def save_tasks_to_db(self, tasks: List[Dict], project_gid: str):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for task in tasks:
            task_gid = task['gid']
            assignee_name = task.get('assignee', {}).get('name', 'Unassigned') if task.get('assignee') else 'Unassigned'
            new_due_on = task.get('due_on', '')
            custom_fields_json = json.dumps(task.get('custom_fields', []))
            custom_fields = task.get('custom_fields', [])

            # Track due_on changes only if it's delayed
            cursor.execute('SELECT due_on FROM tasks WHERE gid = ?', (task_gid,))
            existing = cursor.fetchone()
            old_due_on = existing[0] if existing else ''

            is_delay = self.is_due_date_delayed(old_due_on, new_due_on)
            if existing and is_delay:
                cursor.execute('''
                    INSERT INTO due_date_updates (task_gid, old_due_on, new_due_on, update_date, is_delay)
                    VALUES (?, ?, ?, ?, ?)
                ''', (task_gid, old_due_on, new_due_on, datetime.now().isoformat(), 1))
                self.increment_delay_count(task_gid, custom_fields)

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

    def analyze_due_on_updates(self, project_gid: str):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT d.task_gid, t.name, t.assignee_name, d.old_due_on, d.new_due_on, d.update_date
            FROM due_date_updates d
            JOIN tasks t ON d.task_gid = t.gid
            WHERE t.project_gid = ? AND d.is_delay = 1
            ORDER BY d.update_date
        ''', (project_gid,))

        changes = cursor.fetchall()
        print("\n=== Due Date Delays Detected ===")
        for row in changes:
            print(f"- {row[1]} (Assignee: {row[2]})")
            print(f"  From: {row[3]} → To: {row[4]} at {row[5]}")
        print(f"\nTotal delayed tasks found: {len(changes)}")
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Delay Catcher – Track due_on changes")
    parser.add_argument("--asana-token", required=True)
    parser.add_argument("--workspace-id", default="1203024903921604")
    args = parser.parse_args()

    manager = AsanaManager(args.asana_token, args.workspace_id)

    print("=== Delay Catcher Dev Mode ===")
    projects = manager.get_saved_projects()

    for i, project in enumerate(projects):
        print(f"{i+1}. {project['name']} (Team: {project['team']})")

    choice = int(input("Select a project: ")) - 1
    project_gid = projects[choice]['gid']

#    print("\n1. Update data from Asana")
#    print("2. Analyze due date delays")
#    action = input("Choose action (1/2): ").strip()

#    if action == '1':
#        manager.update_project_data(project_gid)
#    elif action == '2':
#        manager.analyze_due_on_updates(project_gid)
#    else:
#        print("Invalid choice.")

    print("\nAuto-running: Update Asana data...\n")
    manager.update_project_data(project_gid)

    print("\nAuto-running: Analyze due date changes...\n")
    manager.analyze_due_on_updates(project_gid)

if __name__ == "__main__":
    main()
