# workspace_check.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

ASANA_TOKEN = os.getenv("ASANA_TOKEN")
PROJECT_GID = os.getenv("ASANA_TMX_PROJECT_ID")

headers = {
    "Authorization": f"Bearer {ASANA_TOKEN}",
    "Content-Type": "application/json"
}

print("🔍 Checking Asana permissions and workspace information...")
print("=" * 50)

# 1. Check if the token is valid
print("1. Check current user information...")
user_response = requests.get("https://app.asana.com/api/1.0/users/me", headers=headers)
print(f"Status: {user_response.status_code}")
if user_response.status_code == 200:
    user_data = user_response.json()['data']
    print(f"✅ User: {user_data.get('name')} ({user_data.get('email')})")
    print(f"   GID: {user_data.get('gid')}")
else:
    print(f"❌ Failed to retrieve user information: {user_response.json()}")
    exit(1)

print()

# 2. Retrieve user's workspaces
print("2. Get user workspaces...")
workspaces_response = requests.get("https://app.asana.com/api/1.0/workspaces", headers=headers)
print(f"Status: {workspaces_response.status_code}")
if workspaces_response.status_code == 200:
    workspaces = workspaces_response.json()['data']
    print(f"✅ Find {len(workspaces)} workspace(s):")
    for ws in workspaces:
        print(f"   - {ws['name']} (GID: {ws['gid']})")
    
    if workspaces:
        workspace_gid = workspaces[0]['gid']  # Use the first workspace [0]
        print(f"\n📌 Using workspace: {workspaces[0]['name']} ({workspace_gid})")
    else:
        print("❌ No workspaces found.")
        exit(1)
else:
    print(f"❌ Failed to retrieve workspaces: {workspaces_response.json()}")
    exit(1)

print()

# 3. Check project info
print("3. Check project info...")
project_response = requests.get(f"https://app.asana.com/api/1.0/projects/{PROJECT_GID}", headers=headers)
print(f"Status: {project_response.status_code}")
if project_response.status_code == 200:
    project_data = project_response.json()['data']
    print(f"✅ Project: {project_data.get('name')}")
    print(f"   GID: {project_data.get('gid')}")
    print(f"   Workspace: {project_data.get('workspace', {}).get('name')} ({project_data.get('workspace', {}).get('gid')})")
else:
    print(f"❌ Failed to retrieve project info: {project_response.json()}")
    exit(1)

print()

# 4. Check existing webhooks in the workspace
print("4. Check existing webhooks in the workspace...")
webhook_response = requests.get(f"https://app.asana.com/api/1.0/webhooks?workspace={workspace_gid}", headers=headers)
print(f"Status: {webhook_response.status_code}")
if webhook_response.status_code == 200:
    webhooks = webhook_response.json()['data']
    print(f"✅ Found {len(webhooks)} webhooks:")
    for webhook in webhooks:
        print(f"   Target: {webhook.get('target')}")
        print(f"   Resource: {webhook.get('resource', {}).get('gid')} ({webhook.get('resource', {}).get('name')})")
        print(f"   GID: {webhook.get('gid')}")
        print()
    
    # Delete existing webhooks for the same project
    for webhook in webhooks:
        if webhook.get('resource', {}).get('gid') == PROJECT_GID:
            print(f" Deleting existing webhook: {webhook['gid']}")
            delete_response = requests.delete(f"https://app.asana.com/api/1.0/webhooks/{webhook['gid']}", headers=headers)
            print(f" Delete status: {delete_response.status_code}")
else:
    print(f"❌ Failed to check webhooks: {webhook_response.json()}")

print()
print("=" * 50)
print("✅ Check complete! You can now try registering a new webhook.")