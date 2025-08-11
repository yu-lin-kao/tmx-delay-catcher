# register_webhook.py

import os
import requests
from dotenv import load_dotenv
import time

load_dotenv()

ASANA_TOKEN = os.getenv("ASANA_TOKEN")
PROJECT_GID = os.getenv("ASANA_TMX_PROJECT_ID")
WEBHOOK_URL = "https://delay-catcher-tmx.fly.dev/webhook"
WORKSPACE_GID = "1203024903921604"  # Workspace GID obtained from workspace_check.py

headers = {
    "Authorization": f"Bearer {ASANA_TOKEN}",
    "Content-Type": "application/json"
}

print("🚀 Register Asana Webhook")
print("=" * 50)

# 1. Check and clean up existing webhooks (using the correct workspace parameter).
print("1. Checking existing webhooks in the workspace...")
existing_webhooks = requests.get(f"https://app.asana.com/api/1.0/webhooks?workspace={WORKSPACE_GID}", headers=headers)
print(f"Status: {existing_webhooks.status_code}")

if existing_webhooks.status_code == 200:
    webhooks = existing_webhooks.json().get('data', [])
    print(f"Found {len(webhooks)} existing webhooks")
    
    # Delete existing webhooks for the same project
    for webhook in webhooks:
        if webhook.get('resource', {}).get('gid') == PROJECT_GID:
            print(f" Deleting existing webhook: {webhook['gid']}")
            delete_response = requests.delete(f"https://app.asana.com/api/1.0/webhooks/{webhook['gid']}", headers=headers)
            print(f" Delete status: {delete_response.status_code}")
            time.sleep(1)
else:
    print(f"Failed to check existing webhooks: {existing_webhooks.json()}")

print()

# 2. Test webhook URL
print("2. Testing webhook URL...")
test_response = requests.get(WEBHOOK_URL)
print(f"Webhook URL test: {test_response.status_code} - Response length: {len(test_response.text)}")

print()

# 3. Test handshake
print("3. Testing handshake...")
handshake_response = requests.get(WEBHOOK_URL, headers={"X-Hook-Secret": "test_secret_12345"})
print(f"Handshake test: {handshake_response.status_code}")
print(f"Returned secret: '{handshake_response.text}'")
print(f"Content-Type: {handshake_response.headers.get('content-type')}")

print()

# 4. Create webhook
print("4. Creating new webhook...")
payload = {
    "data": {
        "resource": PROJECT_GID,
        "target": WEBHOOK_URL
    }
}

print(f"PROJECT_GID: {PROJECT_GID}")
print(f"WEBHOOK_URL: {WEBHOOK_URL}")
print(f"WORKSPACE_GID: {WORKSPACE_GID}")
print(f"Payload: {payload}")

print("\n🔄 發送註冊請求...")
time.sleep(2)  # Wait a bit

response = requests.post("https://app.asana.com/api/1.0/webhooks", headers=headers, json=payload)

print("\n📊 Registration result:")
print("=" * 30)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")

if response.status_code == 201:
    print("✅ Webhook registered successfully!")
    webhook_data = response.json()['data']
    print(f"   Webhook GID: {webhook_data.get('gid')}")
    print(f"   Target: {webhook_data.get('target')}")
    print(f"   Resource: {webhook_data.get('resource', {}).get('name')}")
else:
    print("❌ Webhook registration failed!")
    
print("\n💡 Tips:")
print("- Now check fly logs to see if there's a handshake request from Asana")
print("- If no request is logged, the issue might be on Asana's network side")
print("- Run: fly logs --app delay-catcher-tmx")