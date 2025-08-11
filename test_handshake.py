# test_handshake.py - Test different handshake formats

import requests

WEBHOOK_URL = "https://delay-catcher-tmx.fly.dev/webhook"

print(" Testing different handshake formats...")
print("=" * 50)

# Test 1: GET request + X-Hook-Secret
print("Test 1: GET request + X-Hook-Secret")
response = requests.get(WEBHOOK_URL, headers={"X-Hook-Secret": "test_secret_get"})
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")
print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
print()

# Test 2: POST request + X-Hook-Secret (empty)
print("Test 2: POST request + X-Hook-Secret (empty)")
response = requests.post(WEBHOOK_URL, headers={"X-Hook-Secret": "test_secret_post"})
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")
print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
print()

# Test 3: POST request + X-Hook-Secret + JSON body
print("Test 3: POST request + X-Hook-Secret + JSON body")
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

# Test 4: POST request + X-Hook-Secret + simulated Asana format
print("Test 4: POST request + X-Hook-Secret + simulated Asana format")
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

print("✅ Test complete!")