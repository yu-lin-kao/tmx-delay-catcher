# workspace_check.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

ASANA_TOKEN = os.getenv("ASANA_TOKEN")
PROJECT_GID = os.getenv("ASANA_PROJECT_ID")

headers = {
    "Authorization": f"Bearer {ASANA_TOKEN}",
    "Content-Type": "application/json"
}

print("🔍 檢查 Asana 權限和工作區信息...")
print("=" * 50)

# 1. 檢查 token 是否有效
print("1. 檢查當前用戶信息...")
user_response = requests.get("https://app.asana.com/api/1.0/users/me", headers=headers)
print(f"Status: {user_response.status_code}")
if user_response.status_code == 200:
    user_data = user_response.json()['data']
    print(f"✅ 用戶: {user_data.get('name')} ({user_data.get('email')})")
    print(f"   GID: {user_data.get('gid')}")
else:
    print(f"❌ 用戶信息獲取失敗: {user_response.json()}")
    exit(1)

print()

# 2. 獲取用戶的工作區
print("2. 獲取用戶工作區...")
workspaces_response = requests.get("https://app.asana.com/api/1.0/workspaces", headers=headers)
print(f"Status: {workspaces_response.status_code}")
if workspaces_response.status_code == 200:
    workspaces = workspaces_response.json()['data']
    print(f"✅ 找到 {len(workspaces)} 個工作區:")
    for ws in workspaces:
        print(f"   - {ws['name']} (GID: {ws['gid']})")
    
    if workspaces:
        workspace_gid = workspaces[0]['gid']  # 使用第一個工作區
        print(f"\n📌 將使用工作區: {workspaces[0]['name']} ({workspace_gid})")
    else:
        print("❌ 沒有找到任何工作區")
        exit(1)
else:
    print(f"❌ 工作區獲取失敗: {workspaces_response.json()}")
    exit(1)

print()

# 3. 檢查項目信息
print("3. 檢查項目信息...")
project_response = requests.get(f"https://app.asana.com/api/1.0/projects/{PROJECT_GID}", headers=headers)
print(f"Status: {project_response.status_code}")
if project_response.status_code == 200:
    project_data = project_response.json()['data']
    print(f"✅ 項目: {project_data.get('name')}")
    print(f"   GID: {project_data.get('gid')}")
    print(f"   工作區: {project_data.get('workspace', {}).get('name')} ({project_data.get('workspace', {}).get('gid')})")
else:
    print(f"❌ 項目信息獲取失敗: {project_response.json()}")
    exit(1)

print()

# 4. 檢查該工作區中的現有 webhooks
print("4. 檢查工作區中的現有 webhooks...")
webhook_response = requests.get(f"https://app.asana.com/api/1.0/webhooks?workspace={workspace_gid}", headers=headers)
print(f"Status: {webhook_response.status_code}")
if webhook_response.status_code == 200:
    webhooks = webhook_response.json()['data']
    print(f"✅ 找到 {len(webhooks)} 個 webhooks:")
    for webhook in webhooks:
        print(f"   - Target: {webhook.get('target')}")
        print(f"     Resource: {webhook.get('resource', {}).get('gid')} ({webhook.get('resource', {}).get('name')})")
        print(f"     GID: {webhook.get('gid')}")
        print()
    
    # 刪除針對同一項目的現有 webhooks
    for webhook in webhooks:
        if webhook.get('resource', {}).get('gid') == PROJECT_GID:
            print(f"🗑️ 刪除現有的 webhook: {webhook['gid']}")
            delete_response = requests.delete(f"https://app.asana.com/api/1.0/webhooks/{webhook['gid']}", headers=headers)
            print(f"   刪除狀態: {delete_response.status_code}")
else:
    print(f"❌ Webhooks 檢查失敗: {webhook_response.json()}")

print()
print("=" * 50)
print("✅ 檢查完成！現在可以嘗試註冊新的 webhook。")