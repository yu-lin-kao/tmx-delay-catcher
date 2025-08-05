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
        for field in custom_fields:
            if 'delay reason' in field.get('name', '').lower():
                field_gid = field['gid']
                enum_options = field.get('enum_options', [])

                if not enum_options:
                    # 若 options 沒附帶在 task API 回傳中，需重新查詢 field 資訊
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
            print(f"❌ Failed to update delay count for {task_gid}. Status: {response.status_code}")
        else:
            print(f"✅ Delay Count incremented for task {task_gid}")

        # 🚨 如果沒有填 delay reason，就自動補上 "Awaiting identify"
        if not self.has_delay_reason(custom_fields):
            self.set_delay_reason_awaiting(task_gid, custom_fields)

    def post_to_sheet(self, payload: Dict):
        SHEET_WEBHOOK = "https://script.google.com/macros/s/AKfycbx6UjuCY18B9ZQhcpTAKKQPM0gAilAlERgk4QLEre75KezshUnt61XMyD5rnNdvxc_EBQ/exec"
        try:
            requests.post(SHEET_WEBHOOK, json=payload, timeout=5)
        except Exception as e:
            print("Sheet webhook error:", e)

    def save_tasks_to_db(self, tasks: List[Dict], project_gid: str):
        conn = sqlite3.connect(DB_PATH)
        conn.execute('PRAGMA journal_mode=WAL')
        cursor = conn.cursor()

        task_map = {t['gid']: t for t in tasks}
        all_delay_reason_changes = []

        for task in tasks:
            task_gid = task['gid']
            assignee = task.get('assignee')
            assignee_name = assignee['name'] if assignee and 'name' in assignee else 'Unassigned'
            new_due_on = task.get('due_on', '')
            custom_fields = task.get('custom_fields', [])
            custom_fields_json = json.dumps(custom_fields)

            # 檢查舊 due date
            cursor.execute('SELECT due_on FROM tasks WHERE gid = ?', (task_gid,))
            existing = cursor.fetchone()
            old_due_on = existing[0] if existing else ''

            # 判斷是否 delay（延後或取消）
            is_delay = self.is_due_date_delayed(old_due_on, new_due_on)

            if existing and (old_due_on != new_due_on) and is_delay:
                # 寫入 due_date_updates
                cursor.execute('''
                    INSERT INTO due_date_updates (task_gid, old_due_on, new_due_on, update_date, is_delay)
                    VALUES (?, ?, ?, ?, ?)
                ''', (task_gid, old_due_on, new_due_on, datetime.now().isoformat(), 1))

                # Delay Count +1，如果沒有 delay reason，補 "Awaiting identify"
                self.increment_delay_count(task_gid, custom_fields)

                # 寫入 Google Sheet
                delay_count = self.get_current_delay_count(custom_fields)
                cursor.execute('SELECT MIN(old_due_on) FROM due_date_updates WHERE task_gid = ?', (task_gid,))
                first_due = cursor.fetchone()[0] or ''
                delay_duration = ''
                if first_due and new_due_on:
                    try:
                        d1 = datetime.fromisoformat(first_due)
                        d2 = datetime.fromisoformat(new_due_on)
                        delay_duration = (d2 - d1).days
                    except:
                        pass

                self.post_to_sheet({
                    "task_gid": task_gid,
                    "task_name": task['name'],
                    "delay_count": delay_count,
                    "new_reason": self.get_current_delay_reason(custom_fields) or "Awaiting identify",
                    "first_due_on": first_due,
                    "latest_due_on": new_due_on,
                    "delay_duration": delay_duration,
                    "updated_at": datetime.now().isoformat(),
                    "updated_by": assignee_name
                })

            # 更新 tasks 表（永遠寫入最新狀態）
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

            # 收集 delay reason 更動
            delay_changes = self.get_delay_reason_changes(task_gid, task)
            all_delay_reason_changes.extend(delay_changes)

        # 處理 delay reason 更動：寫入歷史表 & Google Sheet
        for change in all_delay_reason_changes:
            # always log to Google Sheet
            task_obj = task_map.get(change['task_gid'], {})
            custom_fields = task_obj.get('custom_fields', [])
            new_due_on = task_obj.get('due_on', '')
            delay_count = self.get_current_delay_count(custom_fields)

            cursor.execute('SELECT MIN(old_due_on) FROM due_date_updates WHERE task_gid = ?', (change['task_gid'],))
            first_due = cursor.fetchone()[0] or ''
            delay_duration = ''
            if first_due and new_due_on:
                try:
                    d1 = datetime.fromisoformat(first_due)
                    d2 = datetime.fromisoformat(new_due_on)
                    delay_duration = (d2 - d1).days
                except:
                    pass

            self.post_to_sheet({
                "task_gid": change['task_gid'],
                "task_name": change['task_name'],
                "delay_count": delay_count,
                "new_reason": change['new_reason'],
                "first_due_on": first_due,
                "latest_due_on": new_due_on,
                "delay_duration": delay_duration,
                "updated_at": change['update_date'],
                "updated_by": change['changed_by']
            })

            # 插入歷史紀錄（如果該筆尚未存在）
            cursor.execute('''
                SELECT COUNT(*) FROM delay_reason_updates 
                WHERE task_gid = ? AND old_reason = ? AND new_reason = ? AND update_date = ?
            ''', (change['task_gid'], change['old_reason'], change['new_reason'], change['update_date']))
            already_exists = cursor.fetchone()[0] > 0

            if not already_exists:
                cursor.execute('''
                    INSERT INTO delay_reason_updates
                    (task_gid, old_reason, new_reason, update_date, changed_by)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    change['task_gid'], 
                    change['old_reason'], 
                    change['new_reason'],
                    change['update_date'], 
                    change['changed_by']
                ))

        conn.commit()
        conn.close()


    def get_delay_reason_changes(self, task_gid: str, task: Dict) -> List[Dict]:
        """獲取 delay reason 變更，但不直接操作資料庫"""
        stories = self.get_task_stories(task_gid)
        changes = []
        
        
        for s in stories:
            # 安全地檢查 custom_field
            custom_field = s.get('custom_field')
            if not custom_field:
                continue
                
            field_name = custom_field.get('name', '')
            
            # 檢查是否為 delay reason 的變更
            if (s.get('resource_subtype') == 'enum_custom_field_changed' and
                'delay reason' in field_name.lower()):

                # 安全地獲取舊值和新值
                old_enum_value = s.get('old_enum_value')
                new_enum_value = s.get('new_enum_value')
                
                old_r = old_enum_value.get('name', '') if old_enum_value else ''
                new_r = new_enum_value.get('name', '') if new_enum_value else ''
                
                if old_r != new_r:
                    changes.append({
                        'task_gid': task_gid,
                        'task_name': task['name'],
                        'old_reason': old_r,
                        'new_reason': new_r,
                        'update_date': s.get('created_at', ''),
                        'changed_by': s.get('created_by', {}).get('name', '') if s.get('created_by') else ''
                    })
                        
        return changes

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

    def analyze_delay_reason_updates(self, project_gid: str):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''
            SELECT t.name, d.old_reason, d.new_reason, d.update_date, d.changed_by
            FROM delay_reason_updates d
            JOIN tasks t ON d.task_gid = t.gid
            WHERE t.project_gid = ?
            ORDER BY d.update_date
        ''', (project_gid,))
        rows = cur.fetchall()
        print("\n=== Delay Reason Changes ===")
        for n, old, new, dt, by in rows:
            print(f"- {n}: '{old}' → '{new}' at {dt} by {by}")
        print(f"\nTotal reason updates: {len(rows)}")
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

    print("\nAuto-running: Update Asana data...\n")
    manager.update_project_data(project_gid)

    print("\nAuto-running: Analyze due date changes...\n")
    manager.analyze_due_on_updates(project_gid)

    print("\nAuto-running: Delay reason analysis...\n")
    manager.analyze_delay_reason_updates(project_gid)

if __name__ == "__main__":
    main()