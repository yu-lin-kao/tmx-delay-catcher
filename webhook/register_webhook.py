# register_webhook.py

import os
import requests
from dotenv import load_dotenv
import time

load_dotenv()

ASANA_TOKEN = os.getenv("ASANA_TOKEN")
PROJECT_GID = os.getenv("ASANA_TMX_PROJECT_ID")
WEBHOOK_URL = "https://delay-catcher-tmx.fly.dev/ping?token=es111"
WORKSPACE_GID = "1203024903921604"  # 從 workspace_check.py 得到的工作區 GID

headers = {
    "Authorization": f"Bearer {ASANA_TOKEN}",
    "Content-Type": "application/json"
}

print("🚀 註冊 Asana Webhook")
print("=" * 50)

# 1. 檢查並清理現有 webhooks（使用正確的工作區參數）
print("1. 檢查工作區中的現有 webhooks...")
existing_webhooks = requests.get(f"https://app.asana.com/api/1.0/webhooks?workspace={WORKSPACE_GID}", headers=headers)
print(f"Status: {existing_webhooks.status_code}")

if existing_webhooks.status_code == 200:
    webhooks = existing_webhooks.json().get('data', [])
    print(f"找到 {len(webhooks)} 個現有 webhooks")
    
    # 刪除針對同一項目的現有 webhooks
    for webhook in webhooks:
        if webhook.get('resource', {}).get('gid') == PROJECT_GID:
            print(f"🗑️ 刪除現有 webhook: {webhook['gid']}")
            delete_response = requests.delete(f"https://app.asana.com/api/1.0/webhooks/{webhook['gid']}", headers=headers)
            print(f"   刪除狀態: {delete_response.status_code}")
            time.sleep(1)
else:
    print(f"檢查現有 webhooks 失敗: {existing_webhooks.json()}")

print()

# 2. 測試 webhook URL
print("2. 測試 webhook URL...")
test_response = requests.get(WEBHOOK_URL)
print(f"Webhook URL 測試: {test_response.status_code} - 響應長度: {len(test_response.text)}")

print()

# 3. 測試 handshake 
print("3. 測試 handshake...")
handshake_response = requests.get(WEBHOOK_URL, headers={"X-Hook-Secret": "test_secret_12345"})
print(f"Handshake 測試: {handshake_response.status_code}")
print(f"返回的 secret: '{handshake_response.text}'")
print(f"Content-Type: {handshake_response.headers.get('content-type')}")

print()

# 4. 創建 webhook
print("4. 創建新的 webhook...")
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
time.sleep(2)  # 稍等一下

response = requests.post("https://app.asana.com/api/1.0/webhooks", headers=headers, json=payload)

print("\n📊 註冊結果:")
print("=" * 30)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")

if response.status_code == 201:
    print("✅ Webhook 註冊成功!")
    webhook_data = response.json()['data']
    print(f"   Webhook GID: {webhook_data.get('gid')}")
    print(f"   Target: {webhook_data.get('target')}")
    print(f"   Resource: {webhook_data.get('resource', {}).get('name')}")
else:
    print("❌ Webhook 註冊失敗!")
    
print("\n💡 提示:")
print("- 現在請檢查 fly logs 看看是否有來自 Asana 的 handshake 請求")
print("- 如果沒有任何請求記錄，問題可能在於 Asana 端的網路連接")
print("- 執行: fly logs --app delay-catcher-tmx")