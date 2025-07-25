#!/usr/bin/env python3

import argparse
import requests
import sqlite3
import json
import csv
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re

# Optional imports for plotting functionality
try:
    import matplotlib.pyplot as plt
    import pandas as pd
    PLOTTING_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Plotting functionality disabled due to import error: {e}")
    print("You can still use the script for data analysis and CSV reports.")
    PLOTTING_AVAILABLE = False

BASE_URL = "https://app.asana.com/api/1.0"
DB_PATH = "asana_tasks.db"

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
        """Initialize SQLite database for storing task data"""
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
                last_updated TEXT,
                FOREIGN KEY(project_gid) REFERENCES projects(gid)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_gid TEXT,
                old_custom_fields TEXT,
                new_custom_fields TEXT,
                update_date TEXT,
                FOREIGN KEY(task_gid) REFERENCES tasks(gid)
            )
        ''')
        
        conn.commit()
        conn.close()

    def get_projects(self) -> List[Dict]:
        """Fetch all projects from Asana"""
        params = {"workspace": self.workspace_id}
        response = requests.get(f"{BASE_URL}/projects", headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()['data']
        else:
            print(f"Failed to retrieve projects. Status code: {response.status_code}")
            return []

    def get_project_tasks(self, project_gid: str) -> List[Dict]:
        """Fetch all tasks for a specific project"""
        params = {
            "project": project_gid,
            "opt_fields": "gid,name,assignee.name,completed,completed_at,created_at,modified_at,due_on,notes,permalink_url,custom_fields"
        }
        response = requests.get(f"{BASE_URL}/tasks", headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()['data']
        else:
            print(f"Failed to retrieve tasks for project {project_gid}. Status code: {response.status_code}")
            return []

    def get_task_stories(self, task_gid: str) -> List[Dict]:
        """Fetch stories (including field changes) for a specific task"""
        params = {
            "opt_fields": "gid,created_at,created_by.name,resource_subtype,text,new_enum_value.name,old_enum_value.name,new_multi_enum_value.name,old_multi_enum_value.name,custom_field.name,old_date_value,new_date_value"
        }
        response = requests.get(f"{BASE_URL}/tasks/{task_gid}/stories", headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()['data']
        else:
            print(f"Failed to retrieve stories for task {task_gid}. Status code: {response.status_code}")
            return []

    def get_project_details(self, project_gid: str) -> Dict:
        """Get detailed project information including team"""
        params = {"opt_fields": "gid,name,team.name,created_at,modified_at"}
        response = requests.get(f"{BASE_URL}/projects/{project_gid}", headers=self.headers, params=params)
        
        if response.status_code == 200:
            return response.json()['data']
        else:
            print(f"Failed to retrieve project details. Status code: {response.status_code}")
            return {}

    def save_project_to_db(self, project: Dict):
        """Save project data to database"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        team_name = project.get('team', {}).get('name', 'Unknown') if project.get('team') else 'Unknown'
        
        cursor.execute('''
            INSERT OR REPLACE INTO projects 
            (gid, name, team, created_at, modified_at, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            project['gid'],
            project['name'],
            team_name,
            project.get('created_at', ''),
            project.get('modified_at', ''),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()

    def save_tasks_to_db(self, tasks: List[Dict], project_gid: str):
        """Save task data to database"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        for task in tasks:
            assignee_name = task.get('assignee', {}).get('name', 'Unassigned') if task.get('assignee') else 'Unassigned'
            custom_fields_json = json.dumps(task.get('custom_fields', []))
            
            # Check if task exists to track changes
            cursor.execute('SELECT custom_fields FROM tasks WHERE gid = ?', (task['gid'],))
            existing = cursor.fetchone()
            
            if existing and existing[0] != custom_fields_json:
                # Track custom field changes (for sprint tracking)
                cursor.execute('''
                    INSERT INTO task_updates (task_gid, old_custom_fields, new_custom_fields, update_date)
                    VALUES (?, ?, ?, ?)
                ''', (task['gid'], existing[0], custom_fields_json, datetime.now().isoformat()))
            
            cursor.execute('''
                INSERT OR REPLACE INTO tasks 
                (gid, name, project_gid, assignee_name, completed, completed_at, created_at, 
                 modified_at, due_on, notes, permalink_url, custom_fields, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task['gid'],
                task['name'],
                project_gid,
                assignee_name,
                task.get('completed', False),
                task.get('completed_at', ''),
                task.get('created_at', ''),
                task.get('modified_at', ''),
                task.get('due_on', ''),
                task.get('notes', ''),
                task.get('permalink_url', ''),
                custom_fields_json,
                datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()

    def get_saved_projects(self) -> List[Dict]:
        """Get projects from local database"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT gid, name, team, last_updated FROM projects ORDER BY name')
        projects = []
        for row in cursor.fetchall():
            projects.append({
                'gid': row[0],
                'name': row[1],
                'team': row[2],
                'last_updated': row[3]
            })
        
        conn.close()
        return projects

    def update_project_data(self, project_gid: str):
        """Update project data from Asana API"""
        print(f"Updating project data...")
        
        # Get project details
        project_details = self.get_project_details(project_gid)
        if project_details:
            self.save_project_to_db(project_details)
        
        # Get and save tasks
        tasks = self.get_project_tasks(project_gid)
        if tasks:
            self.save_tasks_to_db(tasks, project_gid)
            print(f"Updated {len(tasks)} tasks")
        else:
            print("No tasks found")

    def analyze_postponed_tasks(self, project_gid: str) -> Tuple[List[Dict], str]:
        """Analyze tasks that have been postponed between sprints"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("DEBUG: Starting postponed tasks analysis using task stories...")
        
        # Get all tasks from the project with custom fields to extract team info
        cursor.execute('''
            SELECT gid, name, assignee_name, custom_fields
            FROM tasks 
            WHERE project_gid = ?
            ORDER BY name
        ''', (project_gid,))
        
        all_tasks = cursor.fetchall()
        print(f"DEBUG: Found {len(all_tasks)} total tasks in project")
        
        postponed_tasks = []
        
        # Analyze each task's stories for sprint changes
        for task_gid, task_name, assignee, custom_fields_json in all_tasks:
            is_lidar = "ONSFT" in task_name and "LiDAR" in task_name
            
            # Extract team information from current custom fields
            custom_fields = json.loads(custom_fields_json) if custom_fields_json else []
            team = self.extract_team_info(custom_fields)
            
            if is_lidar:
                print(f"\nDEBUG: Analyzing LiDAR task: {task_name}")
                print(f"DEBUG: Task GID: {task_gid}")
                print(f"DEBUG: Team: {team}")
            
            # Get stories for this task
            stories = self.get_task_stories(task_gid)
            
            if is_lidar:
                print(f"DEBUG: Found {len(stories)} stories for LiDAR task")
            
            # Look for sprint field changes in stories
            sprint_changes = []
            for story in stories:
                if story.get('resource_subtype') == 'enum_custom_field_changed':
                    custom_field = story.get('custom_field', {})
                    field_name = custom_field.get('name', '').lower()
                    
                    if 'sprint' in field_name:
                        old_value = story.get('old_enum_value', {}).get('name', '') if story.get('old_enum_value') else ''
                        new_value = story.get('new_enum_value', {}).get('name', '') if story.get('new_enum_value') else ''
                        created_at = story.get('created_at', '')
                        created_by = story.get('created_by', {}).get('name', 'Unknown')
                        
                        if old_value and new_value and old_value != new_value:
                            sprint_changes.append({
                                'field_name': custom_field.get('name', ''),
                                'old_value': old_value,
                                'new_value': new_value,
                                'created_at': created_at,
                                'created_by': created_by
                            })
                            
                            if is_lidar:
                                print(f"DEBUG: Found sprint change in LiDAR task:")
                                print(f"  Field: {custom_field.get('name', '')}")
                                print(f"  From: '{old_value}' To: '{new_value}'")
                                print(f"  Date: {created_at}")
                                print(f"  By: {created_by}")
            
            # Check for postponements in sprint changes
            for change in sprint_changes:
                old_num = self.extract_sprint_number(change['old_value'])
                new_num = self.extract_sprint_number(change['new_value'])
                
                if is_lidar:
                    print(f"DEBUG: Sprint numbers - Old: {old_num}, New: {new_num}")
                
                if old_num and new_num and new_num > old_num:
                    postponed_count = new_num - old_num
                    
                    postponed_tasks.append({
                        'task_gid': task_gid,
                        'task_name': task_name,
                        'assignee': assignee or 'Unassigned',
                        'team': team,
                        'from_sprint': change['old_value'],
                        'from_sprint_num': old_num,
                        'to_sprint': change['new_value'],
                        'to_sprint_num': new_num,
                        'postponed_count': postponed_count,
                        'postponed_date': change['created_at'],
                        'changed_by': change['created_by']
                    })
                    
                    if is_lidar:
                        print(f"DEBUG: ✓ LiDAR task added to postponed tasks!")
                        print(f"DEBUG: Postponed by {postponed_count} sprint(s)")
                    
                    print(f"Found postponement: {task_name} moved from {change['old_value']} to {change['new_value']} ({postponed_count} sprint(s))")
        
        print(f"DEBUG: Total postponed tasks found: {len(postponed_tasks)}")
        
        # Generate CSV report
        csv_filename = f"postponed_tasks_{project_gid}_{datetime.now().strftime('%Y%m%d')}.csv"
        with open(csv_filename, 'w', newline='') as csvfile:
            fieldnames = [
                'task_gid', 'task_name', 'assignee', 'team', 
                'from_sprint', 'from_sprint_num', 'to_sprint', 'to_sprint_num', 
                'postponed_count', 'postponed_date', 'changed_by'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for task in postponed_tasks:
                writer.writerow(task)
        
        conn.close()
        return postponed_tasks, csv_filename

    def analyze_due_date_delays(self, project_gid: str) -> Tuple[List[Dict], str]:
        """Analyze tasks with due date delays and delay reasons"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("DEBUG: Starting due date delay analysis using task stories...")
        
        # Get all tasks from the project with custom fields to extract delay info
        cursor.execute('''
            SELECT gid, name, assignee_name, custom_fields, due_on
            FROM tasks 
            WHERE project_gid = ?
            ORDER BY name
        ''', (project_gid,))
        
        all_tasks = cursor.fetchall()
        print(f"DEBUG: Found {len(all_tasks)} total tasks in project")
        
        delayed_tasks = []
        
        # Analyze each task's stories for due date and delay reason changes
        for task_gid, task_name, assignee, custom_fields_json, current_due_date in all_tasks:
            is_lidar = "ONSFT" in task_name and "LiDAR" in task_name
            
            # Extract team and current delay info from custom fields
            custom_fields = json.loads(custom_fields_json) if custom_fields_json else []
            team = self.extract_team_info(custom_fields)
            current_delay_count = self.extract_delay_count(custom_fields)
            current_delay_reason = self.extract_delay_reason(custom_fields)
            
            if is_lidar:
                print(f"\nDEBUG: Analyzing LiDAR task for due date delays: {task_name}")
                print(f"DEBUG: Task GID: {task_gid}")
                print(f"DEBUG: Team: {team}")
                print(f"DEBUG: Current due date: {current_due_date}")
                print(f"DEBUG: Current delay count: {current_delay_count}")
                print(f"DEBUG: Current delay reason: {current_delay_reason}")
            
            # Get stories for this task
            stories = self.get_task_stories(task_gid)
            
            if is_lidar:
                print(f"DEBUG: Found {len(stories)} stories for LiDAR task")
                print("DEBUG: Story types found:")
                for i, story in enumerate(stories):
                    print(f"  Story {i}: {story.get('resource_subtype', 'No subtype')} - {story.get('created_at', 'No date')}")
                    if 'due' in story.get('resource_subtype', '').lower():
                        print(f"    Full story: {story}")
            
            # Look for due date changes and delay reason updates in stories
            due_date_changes = []
            delay_reason_changes = []
            
            for story in stories:
                story_type = story.get('resource_subtype', '')
                created_at = story.get('created_at', '')
                created_by_obj = story.get('created_by', {})
                created_by = created_by_obj.get('name', 'Unknown') if created_by_obj else 'Unknown'
                
                # Debug for LiDAR task
                if is_lidar:
                    print(f"DEBUG: Processing story type: {story_type}")
                
                # Track due date changes
                if story_type == 'due_date_changed':
                    if is_lidar:
                        print(f"DEBUG: Found due_date_changed story!")
                        print(f"DEBUG: Story keys: {list(story.keys())}")
                    
                    old_date = story.get('old_date_value', '')
                    new_date = story.get('new_date_value', '')
                    
                    if is_lidar:
                        print(f"DEBUG: old_date_value: {old_date}")
                        print(f"DEBUG: new_date_value: {new_date}")
                    
                    if old_date and new_date:
                        # Check if new date is later than old date (delay)
                        try:
                            old_dt = datetime.fromisoformat(old_date.replace('Z', '+00:00'))
                            new_dt = datetime.fromisoformat(new_date.replace('Z', '+00:00'))
                            
                            if new_dt > old_dt:
                                due_date_changes.append({
                                    'old_due_date': old_date,
                                    'new_due_date': new_date,
                                    'created_at': created_at,
                                    'created_by': created_by,
                                    'delay_days': (new_dt - old_dt).days
                                })
                                
                                if is_lidar:
                                    print(f"DEBUG: Found due date delay in LiDAR task:")
                                    print(f"  From: {old_date} To: {new_date}")
                                    print(f"  Delay: {(new_dt - old_dt).days} days")
                                    print(f"  Date: {created_at}")
                                    print(f"  By: {created_by}")
                        except Exception as e:
                            if is_lidar:
                                print(f"DEBUG: Error parsing dates: {e}")
                    elif is_lidar:
                        print(f"DEBUG: Missing old_date or new_date values")
                
                # Track delay reason changes
                elif story_type == 'multi_enum_custom_field_changed' or story_type == 'enum_custom_field_changed':
                    custom_field = story.get('custom_field', {})
                    field_name = custom_field.get('name', '').lower()
                    
                    if 'delay reason' in field_name:
                        old_value = self.extract_enum_value_from_story(story, 'old')
                        new_value = self.extract_enum_value_from_story(story, 'new')
                        
                        if new_value:  # Any update to delay reason
                            delay_reason_changes.append({
                                'old_delay_reason': old_value,
                                'new_delay_reason': new_value,
                                'created_at': created_at,
                                'created_by': created_by
                            })
                            
                            if is_lidar:
                                print(f"DEBUG: Found delay reason change in LiDAR task:")
                                print(f"  From: '{old_value}' To: '{new_value}'")
                                print(f"  Date: {created_at}")
                                print(f"  By: {created_by}")
            
            # Record delays and delay reason updates
            for change in due_date_changes:
                delayed_tasks.append({
                    'task_gid': task_gid,
                    'task_name': task_name,
                    'assignee': assignee or 'Unassigned',
                    'team': team,
                    'old_due_date': change['old_due_date'],
                    'new_due_date': change['new_due_date'],
                    'delay_days': change['delay_days'],
                    'current_delay_count': current_delay_count,
                    'current_delay_reason': current_delay_reason,
                    'change_type': 'due_date_delay',
                    'change_date': change['created_at'],
                    'changed_by': change['created_by']
                })
                
                if is_lidar:
                    print(f"DEBUG: ✓ LiDAR due date delay added to results!")
            
            for change in delay_reason_changes:
                delayed_tasks.append({
                    'task_gid': task_gid,
                    'task_name': task_name,
                    'assignee': assignee or 'Unassigned',
                    'team': team,
                    'old_due_date': current_due_date or '',
                    'new_due_date': current_due_date or '',
                    'delay_days': 0,
                    'current_delay_count': current_delay_count,
                    'current_delay_reason': current_delay_reason,
                    'old_delay_reason': change['old_delay_reason'],
                    'new_delay_reason': change['new_delay_reason'],
                    'change_type': 'delay_reason_update',
                    'change_date': change['created_at'],
                    'changed_by': change['created_by']
                })
                
                if is_lidar:
                    print(f"DEBUG: ✓ LiDAR delay reason change added to results!")
        
        print(f"DEBUG: Total delayed tasks/updates found: {len(delayed_tasks)}")
        
        # Generate CSV report
        csv_filename = f"due_date_delays_{project_gid}_{datetime.now().strftime('%Y%m%d')}.csv"
        with open(csv_filename, 'w', newline='') as csvfile:
            fieldnames = [
                'task_gid', 'task_name', 'assignee', 'team', 
                'old_due_date', 'new_due_date', 'delay_days',
                'current_delay_count', 'current_delay_reason',
                'old_delay_reason', 'new_delay_reason',
                'change_type', 'change_date', 'changed_by'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for task in delayed_tasks:
                writer.writerow(task)
        
        conn.close()
        return delayed_tasks, csv_filename

    def extract_sprint_info(self, custom_fields: List[Dict]) -> Optional[str]:
        """Extract sprint information from custom fields"""
        for field in custom_fields:
            field_name = field.get('name', '').lower()
            # Look for fields containing "sprint"
            if 'sprint' in field_name:
                if field.get('enum_value'):
                    return field['enum_value'].get('name', '')
                elif field.get('text_value'):
                    return field['text_value']
        return None

    def extract_team_info(self, custom_fields: List[Dict]) -> str:
        """Extract team information from custom fields"""
        for field in custom_fields:
            field_name = field.get('name', '').lower()
            # Look for team field
            if 'team' in field_name:
                if field.get('multi_enum_values'):
                    # Handle multi-enum team field
                    teams = [val.get('name', '') for val in field['multi_enum_values']]
                    return ', '.join(teams) if teams else 'Unknown'
                elif field.get('enum_value'):
                    return field['enum_value'].get('name', 'Unknown')
                elif field.get('text_value'):
                    return field['text_value']
        return 'Unknown'

    def extract_delay_count(self, custom_fields: List[Dict]) -> int:
        """Extract delay count from custom fields"""
        for field in custom_fields:
            field_name = field.get('name', '').lower()
            if 'delay count' in field_name:
                return field.get('number_value', 0) or 0
        return 0

    def extract_delay_reason(self, custom_fields: List[Dict]) -> str:
        """Extract delay reason from custom fields"""
        for field in custom_fields:
            field_name = field.get('name', '').lower()
            if 'delay reason' in field_name:
                if field.get('multi_enum_values'):
                    reasons = [val.get('name', '') for val in field['multi_enum_values']]
                    return ', '.join(reasons) if reasons else ''
                elif field.get('enum_value'):
                    return field['enum_value'].get('name', '')
        return ''

    def extract_enum_value_from_story(self, story: Dict, value_type: str) -> str:
        """Extract enum value from story (old or new)"""
        if value_type == 'old':
            if story.get('old_multi_enum_value'):
                return ', '.join([val.get('name', '') for val in story['old_multi_enum_value']])
            elif story.get('old_enum_value'):
                return story['old_enum_value'].get('name', '')
        else:  # new
            if story.get('new_multi_enum_value'):
                return ', '.join([val.get('name', '') for val in story['new_multi_enum_value']])
            elif story.get('new_enum_value'):
                return story['new_enum_value'].get('name', '')
        return ''

    def extract_sprint_number(self, sprint_name: str) -> Optional[int]:
        """Extract sprint number from sprint name"""
        if not sprint_name:
            return None
        
        # Look for "Sprint X" pattern (case insensitive)
        match = re.search(r'sprint\s*(\d+)', sprint_name.lower())
        if match:
            return int(match.group(1))
        
        # Look for any number in the string as fallback
        match = re.search(r'(\d+)', sprint_name)
        if match:
            return int(match.group(1))
        
        return None

    def plot_postponed_tasks(self, postponed_tasks: List[Dict], project_name: str):
        """Create plots for postponed tasks analysis"""
        if not PLOTTING_AVAILABLE:
            print("Plotting functionality not available. Please install matplotlib and pandas.")
            return
            
        if not postponed_tasks:
            print("No postponed tasks found")
            return
        
        df = pd.DataFrame(postponed_tasks)
        
        # Plot by team/assignee
        plt.figure(figsize=(12, 8))
        
        # Count postponements by assignee
        assignee_counts = df['assignee'].value_counts()
        
        plt.subplot(2, 2, 1)
        assignee_counts.plot(kind='bar')
        plt.title('Postponed Tasks by Assignee')
        plt.xlabel('Assignee')
        plt.ylabel('Number of Postponed Tasks')
        plt.xticks(rotation=45)
        
        # Timeline of postponements
        plt.subplot(2, 2, 2)
        df['postponed_date'] = pd.to_datetime(df['postponed_date'])
        df['month'] = df['postponed_date'].dt.to_period('M')
        monthly_counts = df['month'].value_counts().sort_index()
        monthly_counts.plot(kind='line', marker='o')
        plt.title('Postponements Over Time')
        plt.xlabel('Month')
        plt.ylabel('Number of Postponements')
        plt.xticks(rotation=45)
        
        # Sprint transition analysis
        plt.subplot(2, 2, 3)
        sprint_transitions = df.groupby(['from_sprint', 'to_sprint']).size().reset_index(name='count')
        if len(sprint_transitions) > 0:
            top_transitions = sprint_transitions.nlargest(10, 'count')
            transition_labels = [f"{row['from_sprint']} → {row['to_sprint']}" for _, row in top_transitions.iterrows()]
            plt.bar(range(len(top_transitions)), top_transitions['count'])
            plt.title('Top Sprint Transitions')
            plt.xlabel('Sprint Transition')
            plt.ylabel('Count')
            plt.xticks(range(len(top_transitions)), transition_labels, rotation=45, ha='right')
        
        plt.tight_layout()
        plot_filename = f"postponed_analysis_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.png"
        plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
        plt.show()
        
        print(f"Plot saved as: {plot_filename}")

    def generate_monthly_metrics(self, project_gid: str) -> str:
        """Generate monthly performance metrics"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get task completion data
        cursor.execute('''
            SELECT name, assignee_name, completed, completed_at, created_at, due_on
            FROM tasks 
            WHERE project_gid = ? AND completed_at IS NOT NULL AND completed_at != ''
            ORDER BY completed_at
        ''', (project_gid,))
        
        completed_tasks = cursor.fetchall()
        
        # Get project name
        cursor.execute('SELECT name FROM projects WHERE gid = ?', (project_gid,))
        result = cursor.fetchone()
        project_name = result[0] if result else 'Unknown Project'
        
        conn.close()
        
        if not completed_tasks:
            print("No completed tasks found for metrics analysis")
            return ""
        
        if not PLOTTING_AVAILABLE:
            print("Advanced metrics require pandas/matplotlib. Generating basic CSV report only.")
            # Generate basic CSV without pandas
            report_filename = f"basic_metrics_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv"
            with open(report_filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Task Name', 'Assignee', 'Completed At', 'Created At'])
                for task in completed_tasks:
                    writer.writerow(task[:4])  # name, assignee, completed, completed_at
            print(f"Basic metrics saved as: {report_filename}")
            return report_filename
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame(completed_tasks, columns=['name', 'assignee', 'completed', 'completed_at', 'created_at', 'due_on'])
        df['completed_at'] = pd.to_datetime(df['completed_at'])
        df['created_at'] = pd.to_datetime(df['created_at'])
        df['due_on'] = pd.to_datetime(df['due_on'])
        
        # Calculate cycle time (creation to completion)
        df['cycle_time_days'] = (df['completed_at'] - df['created_at']).dt.days
        
        # Monthly aggregations
        df['completion_month'] = df['completed_at'].dt.to_period('M')
        monthly_metrics = df.groupby('completion_month').agg({
            'name': 'count',
            'cycle_time_days': ['mean', 'median'],
            'assignee': 'nunique'
        }).round(2)
        
        # Team performance
        team_metrics = df.groupby('assignee').agg({
            'name': 'count',
            'cycle_time_days': ['mean', 'median']
        }).round(2)
        
        # Generate report
        report_filename = f"monthly_metrics_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv"
        
        with open(report_filename, 'w', newline='') as csvfile:
            csvfile.write(f"Monthly Metrics Report for {project_name}\n")
            csvfile.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            csvfile.write("Monthly Completion Summary:\n")
            monthly_metrics.to_csv(csvfile)
            
            csvfile.write("\n\nTeam Performance:\n")
            team_metrics.to_csv(csvfile)
        
        # Create visualization
        plt.figure(figsize=(15, 10))
        
        # Monthly completions
        plt.subplot(2, 3, 1)
        monthly_completions = monthly_metrics[('name', 'count')]
        monthly_completions.plot(kind='bar')
        plt.title('Tasks Completed per Month')
        plt.xlabel('Month')
        plt.ylabel('Tasks Completed')
        plt.xticks(rotation=45)
        
        # Average cycle time
        plt.subplot(2, 3, 2)
        avg_cycle_time = monthly_metrics[('cycle_time_days', 'mean')]
        avg_cycle_time.plot(kind='line', marker='o')
        plt.title('Average Cycle Time per Month')
        plt.xlabel('Month')
        plt.ylabel('Days')
        plt.xticks(rotation=45)
        
        # Team productivity
        plt.subplot(2, 3, 3)
        team_completions = team_metrics[('name', 'count')].sort_values(ascending=False)
        team_completions.plot(kind='bar')
        plt.title('Tasks Completed by Team Member')
        plt.xlabel('Team Member')
        plt.ylabel('Tasks Completed')
        plt.xticks(rotation=45)
        
        # Team cycle times
        plt.subplot(2, 3, 4)
        team_cycle_times = team_metrics[('cycle_time_days', 'mean')].sort_values()
        team_cycle_times.plot(kind='bar')
        plt.title('Average Cycle Time by Team Member')
        plt.xlabel('Team Member')
        plt.ylabel('Days')
        plt.xticks(rotation=45)
        
        # Completion trend
        plt.subplot(2, 3, 5)
        df.set_index('completed_at')['name'].resample('W').count().plot()
        plt.title('Weekly Completion Trend')
        plt.xlabel('Week')
        plt.ylabel('Tasks Completed')
        
        plt.tight_layout()
        plot_filename = f"monthly_metrics_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.png"
        plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
        plt.show()
        
        print(f"Monthly metrics report saved as: {report_filename}")
        print(f"Metrics plot saved as: {plot_filename}")
        
        return report_filename

def select_project(asana_manager: AsanaManager) -> Optional[str]:
    """Interactive project selection"""
    projects = asana_manager.get_projects()
    if not projects:
        print("No projects found")
        return None
    
    # Sort projects alphabetically
    projects.sort(key=lambda x: x['name'].lower())
    
    print("\nAvailable Projects:")
    for i, project in enumerate(projects, 1):
        print(f"{i}. {project['name']}")
    
    while True:
        try:
            choice = int(input(f"\nSelect a project (1-{len(projects)}): ")) - 1
            if 0 <= choice < len(projects):
                return projects[choice]['gid']
            else:
                print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number.")

def processing_menu(asana_manager: AsanaManager, project_gid: str):
    """Processing tools menu"""
    # Get project name for display
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM projects WHERE gid = ?', (project_gid,))
    result = cursor.fetchone()
    project_name = result[0] if result else 'Unknown Project'
    conn.close()
    
    while True:
        print(f"\nProcessing Tools Menu - {project_name}")
        print("1. Track postponed tasks (Sprint analysis)")
        print("2. Track due date delays and delay reasons")
        print("3. Generate monthly metrics")
        print("4. Back to main menu")
        
        choice = input("Select an option (1-4): ").strip()
        
        if choice == '1':
            print("\nAnalyzing postponed tasks...")
            postponed_tasks, csv_file = asana_manager.analyze_postponed_tasks(project_gid)
            print(f"Found {len(postponed_tasks)} postponed tasks")
            print(f"CSV report saved as: {csv_file}")
            
            if postponed_tasks and PLOTTING_AVAILABLE:
                plot_choice = input("Generate plots? (y/n): ").strip().lower()
                if plot_choice == 'y':
                    asana_manager.plot_postponed_tasks(postponed_tasks, project_name)
            elif postponed_tasks and not PLOTTING_AVAILABLE:
                print("Plotting not available. CSV report generated only.")
        
        elif choice == '2':
            print("\nAnalyzing due date delays and delay reasons...")
            delayed_tasks, csv_file = asana_manager.analyze_due_date_delays(project_gid)
            print(f"Found {len(delayed_tasks)} delay events")
            print(f"CSV report saved as: {csv_file}")
        
        elif choice == '3':
            print("\nGenerating monthly metrics...")
            report_file = asana_manager.generate_monthly_metrics(project_gid)
            if report_file:
                print(f"Metrics analysis completed")
        
        elif choice == '4':
            break
        
        else:
            print("Invalid choice. Please try again.")

def main():
    parser = argparse.ArgumentParser(description="Interactive Asana Project Manager")
    parser.add_argument("--asana-token", help="Your Asana personal access token", required=True)
    parser.add_argument("--workspace-id", help="Asana workspace ID", default="1203024903921604")
    args = parser.parse_args()
    
    asana_manager = AsanaManager(args.asana_token, args.workspace_id)
    
    print("=== Interactive Asana Project Manager ===")
    
    while True:
        print("\nMain Menu:")
        print("1. Select and work with a project")
        print("2. Exit")
        
        choice = input("Select an option (1-2): ").strip()
        
        if choice == '1':
            project_gid = select_project(asana_manager)
            if not project_gid:
                continue
            
            # Check if project data exists locally
            saved_projects = asana_manager.get_saved_projects()
            project_exists = any(p['gid'] == project_gid for p in saved_projects)
            
            if not project_exists:
                print("\nFirst time working with this project. Downloading task data...")
                asana_manager.update_project_data(project_gid)
                print("Project data saved locally.")
                processing_menu(asana_manager, project_gid)
            else:
                print("\nProject data found locally.")
                print("1. Update database from Asana")
                print("2. Go to processing tools")
                
                sub_choice = input("Select an option (1-2): ").strip()
                
                if sub_choice == '1':
                    asana_manager.update_project_data(project_gid)
                    print("Database updated.")
                    processing_menu(asana_manager, project_gid)
                elif sub_choice == '2':
                    processing_menu(asana_manager, project_gid)
                else:
                    print("Invalid choice.")
        
        elif choice == '2':
            print("Goodbye!")
            break
        
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main()