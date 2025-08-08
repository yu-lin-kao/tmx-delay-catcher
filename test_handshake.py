#!/usr/bin/env python3
# test_handshake.py - 測試不同的 handshake 格式

import requests

WEBHOOK_URL = "https://delay-catcher-tmx.fly.dev/webhook"

print("🧪 測試不同的 handshake 方法...")
print("=" * 50)

# 測試 1: GET 請求 + X-Hook-Secret
print("1. 測試 GET 請求 + X-Hook-Secret")
response = requests.get(WEBHOOK_URL, headers={"X-Hook-Secret": "test_secret_get"})
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")
print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
print()

# 測試 2: POST 請求 + X-Hook-Secret (空 body)
print("2. 測試 POST 請求 + X-Hook-Secret (空 body)")
response = requests.post(WEBHOOK_URL, headers={"X-Hook-Secret": "test_secret_post"})
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")
print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
print()

# 測試 3: POST 請求 + X-Hook-Secret + JSON body
print("3. 測試 POST 請求 + X-Hook-Secret + JSON body")
response = requests.post(
    WEBHOOK_URL, 
    headers={
        "X-Hook-Secret": "test_secret_post_json",
        "Content-Type": "application/json"
    },
    json={}
)
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")
print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
print()

# 測試 4: POST 請求 + X-Hook-Secret + 模擬 Asana 格式
print("4. 測試 POST 請求 + X-Hook-Secret + 模擬 Asana 註冊格式")
response = requests.post(
    WEBHOOK_URL,
    headers={
        "X-Hook-Secret": "asana_test_secret_12345",
        "Content-Type": "application/json",
        "User-Agent": "AsanaBot/1.0"
    },
    json={"test": "handshake"}
)
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")
print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
print()

print("✅ 測試完成!")