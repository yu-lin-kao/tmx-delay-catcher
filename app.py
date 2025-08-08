#app.py

from flask import Flask, request, jsonify, make_response
from delay_catcher_tmx import main as run_delay_catcher

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "message": "Delay Catcher TMX Webhook is running!"}), 200

@app.route("/webhook", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def webhook():
    # 記錄所有請求的詳細信息
    import json
    print(f"🌐 收到 {request.method} 請求到 /webhook")
    print(f"📋 所有 Headers:")
    for key, value in request.headers.items():
        print(f"   {key}: {value}")
    
    print(f"🔍 Request Info:")
    print(f"   Remote Address: {request.environ.get('REMOTE_ADDR', 'Unknown')}")
    print(f"   User Agent: {request.headers.get('User-Agent', 'Unknown')}")
    print(f"   Content Type: {request.headers.get('Content-Type', 'None')}")
    print(f"   Content Length: {request.headers.get('Content-Length', 'None')}")
    
    # 記錄請求體（如果有的話）
    if request.method in ['POST', 'PUT', 'PATCH']:
        try:
            if request.is_json:
                print(f"📄 JSON Body: {json.dumps(request.get_json(), indent=2)}")
            elif request.data:
                print(f"📄 Raw Body: {request.data}")
        except Exception as e:
            print(f"❌ Error reading body: {e}")
    
    print("=" * 60)
    
    # Asana webhook secret verification (適用於註冊時的 handshake)
    if "X-Hook-Secret" in request.headers:
        secret = request.headers["X-Hook-Secret"]
        print(f"🔐 檢測到 X-Hook-Secret: {secret}")
        print(f"🤝 返回 handshake secret: {secret}")
        
        response = make_response(secret, 200)
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        response.headers['Content-Length'] = str(len(secret))
        response.headers['X-Hook-Secret'] = secret  # 🔑 關鍵：Asana 可能要求你 echo 回這個 header！
        return response
    
    # Handle GET request for webhook verification
    if request.method == "GET":
        print("✅ 處理 GET 請求 - 返回 webhook ready 狀態")
        return jsonify({"status": "webhook_ready", "message": "Webhook endpoint is ready"}), 200
    
    # Handle POST request for actual webhook data
    if request.method == "POST":

        data = request.json
        print("✅ Webhook Received:", data)
        
        try:
            print("🔄 Executing delay_catcher_tmx...")
            result = run_delay_catcher()
            print("✅ delay_catcher_tmx executed successfully")
            
            return jsonify({
                "status": "success", 
                "message": "delay_catcher_tmx executed successfully"
            }), 200
            
        except Exception as e:
            print(f"❌ Error in delay_catcher_tmx: {str(e)}")
            return jsonify({
                "status": "error", 
                "message": f"Execution error: {str(e)}"
            }), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Starting Delay Catcher TMX Webhook on 0.0.0.0:{port}")
    print("📬 Webhook Received!")

    app.run(host="0.0.0.0", port=port, debug=False)