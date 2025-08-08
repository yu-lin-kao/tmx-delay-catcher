# delay_catcher_dev.py
# Purpose: Track and analyze due_on changes in Asana tasks, increment Delay Count, and log Delay Reason changes

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
            "opt_fields": "gid,name,assignee.name,completed,completed_at,created_at,modified_at,due_on,notes,permalink_url,custom_fields"
        }
        response = requests.get(f"{BASE_URL}/projects/{project_gid}/tasks", headers=self.headers, params=params)
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

    def get_task_by_gid(self, task_gid: str) -> Optional[Dict]:
        response = requests.get(f"{BASE_URL}/tasks/{task_gid}?opt_fields=custom_fields", headers=self.headers)
        if response.status_code == 200:
            return response.json().get('data')
        else:
            print(f"❌ Failed to fetch task {task_gid} for updated fields.")
            return None

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
        SHEET_WEBHOOK = os.getenv("SHEET_WEBHOOK_URL")
        try:
            requests.post(SHEET_WEBHOOK, json=payload, timeout=5)
        except Exception as e:
            print("Sheet webhook error:", e)

    def save_tasks_to_db(self, tasks: List[Dict], project_gid: str):
        conn = sqlite3.connect(DB_PATH)
        conn.execute('PRAGMA journal_mode=WAL')
        cursor = conn.cursor()

        for task in tasks:
            task_gid = task['gid']
            assignee = task.get('assignee')
            assignee_name = assignee['name'] if assignee and 'name' in assignee else 'Unassigned'
            new_due_on = task.get('due_on', '')
            custom_fields = task.get('custom_fields', [])
            custom_fields_json = json.dumps(custom_fields)
            
            # 獲取當前的 delay reason
            current_delay_reason = self.get_current_delay_reason(custom_fields)

            # ===== 1. 檢查並處理 due_on 變更 =====
            cursor.execute('SELECT due_on FROM tasks WHERE gid = ?', (task_gid,))
            existing = cursor.fetchone()
            old_due_on = existing[0] if existing else ''

            # 只處理延後或取消的情況
            if old_due_on != new_due_on and self.is_due_date_delayed(old_due_on, new_due_on):
                self._handle_due_date_delay(cursor, task, task_gid, old_due_on, new_due_on, assignee_name, custom_fields)

            # ===== 2. 檢查並處理 delay reason 變更 =====
            cursor.execute('SELECT custom_fields FROM tasks WHERE gid = ?', (task_gid,))
            existing_task = cursor.fetchone()
            old_delay_reason = ""
            
            if existing_task and existing_task[0]:
                try:
                    old_custom_fields = json.loads(existing_task[0])
                    old_delay_reason = self.get_current_delay_reason(old_custom_fields) or ""
                except:
                    old_delay_reason = ""

            # 只有當 delay reason 真的有變化時才處理
            if old_delay_reason != (current_delay_reason or "") and current_delay_reason:
                self._handle_delay_reason_change(cursor, task, task_gid, old_delay_reason, current_delay_reason, assignee_name)

            # ===== 3. 更新或插入 task 資料 =====
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

    def _handle_due_date_delay(self, cursor, task: Dict, task_gid: str, old_due_on: str, new_due_on: str, assignee_name: str, custom_fields: List[Dict]):
        """處理 due date 延後的邏輯"""

        # 🧠 避免重複記錄相同的 due_on 變化
        cursor.execute('''
            SELECT COUNT(*) FROM due_date_updates
            WHERE task_gid = ? AND old_due_on = ? AND new_due_on = ?
        ''', (task_gid, old_due_on, new_due_on))
        already_logged = cursor.fetchone()[0]

        if already_logged:
            if getattr(self, 'debug_mode', False):
                print(f"⏩ Skipping duplicate due date log: {task['name']} {old_due_on} → {new_due_on}")
            return

        print(f"🔄 Due date delayed for task {task['name']}: {old_due_on} → {new_due_on}")
        
        modifier_info = self._get_latest_due_date_modifier(task_gid)

        cursor.execute('''
            INSERT INTO due_date_updates (task_gid, old_due_on, new_due_on, update_date, is_delay)
            VALUES (?, ?, ?, ?, ?)
        ''', (task_gid, old_due_on, new_due_on, modifier_info['updated_at'], 1))

        self.increment_delay_count(task_gid, custom_fields)
        self._log_to_spreadsheet(cursor, task, task_gid, modifier_info, "due_date_change")
    
    def _handle_delay_reason_change(self, cursor, task: Dict, task_gid: str, old_reason: str, new_reason: str, assignee_name: str):
        """處理 delay reason 變更的邏輯"""

        # 🧠 避免重複記錄相同的變化
        cursor.execute('''
            SELECT COUNT(*) FROM delay_reason_updates
            WHERE task_gid = ? AND old_reason = ? AND new_reason = ?
        ''', (task_gid, old_reason, new_reason))
        already_logged = cursor.fetchone()[0]

        if already_logged:
            if getattr(self, 'debug_mode', False):
                print(f"⏩ Skipping duplicate delay reason log: {task['name']} {old_reason} → {new_reason}")
            return

        print(f"🔄 Delay reason changed for task {task['name']}: '{old_reason}' → '{new_reason}'")
        
        modifier_info = self._get_latest_delay_reason_modifier(task_gid, new_reason)

        cursor.execute('''
            INSERT INTO delay_reason_updates 
            (task_gid, old_reason, new_reason, update_date, changed_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (task_gid, old_reason, new_reason, modifier_info['updated_at'], modifier_info['updated_by']))

        self._log_to_spreadsheet(cursor, task, task_gid, modifier_info, "delay_reason_change")

    def _log_to_spreadsheet(self, cursor, task: Dict, task_gid: str, modifier_info: Dict, change_type: str):
        """統一的 Google Spreadsheet 記錄邏輯"""
        # 獲取最新的 task 資料（包含更新後的 delay count 等）
        updated_task = self.get_task_by_gid(task_gid)
        if not updated_task:
            print(f"❌ Failed to get updated task data for {task_gid}")
            return

        updated_fields = updated_task.get('custom_fields', [])
        delay_count = self.get_current_delay_count(updated_fields)
        current_delay_reason = self.get_current_delay_reason(updated_fields) or "Awaiting identify"
        
        # 獲取最早的 due date
        cursor.execute('SELECT MIN(old_due_on) FROM due_date_updates WHERE task_gid = ?', (task_gid,))
        first_due_result = cursor.fetchone()
        first_due_on = first_due_result[0] if first_due_result and first_due_result[0] else ''
        
        latest_due_on = task.get('due_on', '')
        
        # 計算延遲天數
        delay_duration = ''
        if first_due_on and latest_due_on:
            try:
                d1 = datetime.fromisoformat(first_due_on)
                d2 = datetime.fromisoformat(latest_due_on)
                delay_duration = (d2 - d1).days
            except Exception as e:
                print(f"⚠️ Error calculating delay duration: {e}")

        # 發送到 Google Spreadsheet
        payload = {
            "task_gid": task_gid,
            "task_name": task['name'],
            "delay_count": delay_count,
            "new_reason": current_delay_reason,
            "first_due_on": first_due_on,
            "latest_due_on": latest_due_on,
            "delay_duration": delay_duration,
            "updated_at": modifier_info['updated_at'],  # Asana 的修改時間
            "updated_by": modifier_info['updated_by'],  # 實際修改的人
            "change_type": change_type  # 標記是什麼類型的變更
        }
        
        self.post_to_sheet(payload)
        print(f"📊 Logged to spreadsheet: {task['name']} ({change_type})")

    def _get_latest_due_date_modifier(self, task_gid: str) -> Dict[str, str]:
        """從 task stories 獲取最新的 due date 修改者資訊"""
        stories = self.get_task_stories(task_gid)
        
        # 尋找最新的 due date 變更
        for story in sorted(stories, key=lambda x: x.get('created_at', ''), reverse=True):
            if story.get('resource_subtype') == 'due_date_changed':
                created_by = story.get('created_by', {})
                return {
                    'updated_at': story.get('created_at', datetime.now().isoformat()),
                    'updated_by': created_by.get('name', 'Unknown') if created_by else 'Unknown'
                }
        
        # 如果找不到 due date 變更記錄，使用 task 的 modified_at
        return {
            'updated_at': datetime.now().isoformat(),
            'updated_by': 'System'
        }

    def _get_latest_delay_reason_modifier(self, task_gid: str, new_reason: str) -> Dict[str, str]:
        """從 task stories 獲取最新的 delay reason 修改者資訊"""
        stories = self.get_task_stories(task_gid)
        
        # 尋找最新的 delay reason 變更
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
        
        # 如果找不到對應的變更記錄，使用當前時間
        return {
            'updated_at': datetime.now().isoformat(),
            'updated_by': 'System'
        }


    def get_delay_reason_changes(self, task_gid: str, task: Dict) -> List[Dict]:
        stories = self.get_task_stories(task_gid)
        changes = []

        # 取得上次處理這個 task 的時間（用來過濾）
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT last_updated FROM tasks WHERE gid = ?", (task_gid,))
        row = cursor.fetchone()
        last_updated = datetime.min
        if row and row[0]:
            try:
                last_updated = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
            except:
                pass
        conn.close()

        for s in stories:
            custom_field = s.get('custom_field')
            if not custom_field:
                continue

            field_name = custom_field.get('name', '').lower()
            created_at = s.get('created_at', '')
            try:
                created_at_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                continue

            # ✅ 過濾掉「上次處理之前就已經存在」的變更
            if created_at_dt <= last_updated:
                continue

            if s.get('resource_subtype') == 'enum_custom_field_changed' and 'delay reason' in field_name:
                old_enum = s.get('old_enum_value')
                new_enum = s.get('new_enum_value')
                old_r = old_enum.get('name', '') if old_enum else ''
                new_r = new_enum.get('name', '') if new_enum else ''

                if old_r != new_r:
                    changes.append({
                        'task_gid': task_gid,
                        'task_name': task['name'],
                        'old_reason': old_r,
                        'new_reason': new_r,
                        'update_date': created_at,
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
    parser.add_argument("--asana-token", default=os.getenv("ASANA_TOKEN")) # Asana Token
    parser.add_argument("--workspace-id", default=os.getenv("ASANA_WORKSPACE_ID"))
    args = parser.parse_args()

    manager = AsanaManager(args.asana_token, args.workspace_id)

    print("=== Delay Catcher Dev Mode ===")
    projects = manager.get_saved_projects()

    for i, project in enumerate(projects):
        print(f"{i+1}. {project['name']} (Team: {project['team']})")

    # choice = int(input("Select a project: ")) - 1
    # project_gid = projects[choice]['gid']
    
    project_gid = os.getenv("ASANA_TMX_PROJECT_ID")

    print("\nAuto-running: Update Asana data...\n")
    manager.update_project_data(project_gid)

    # print("\nAuto-running: Analyze due date changes...\n")
    # manager.analyze_due_on_updates(project_gid)

    # print("\nAuto-running: Delay reason analysis...\n")
    # manager.analyze_delay_reason_updates(project_gid)

if __name__ == "__main__":
    main()