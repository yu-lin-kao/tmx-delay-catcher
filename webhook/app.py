#app.py

from flask import Flask, request, jsonify, make_response
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from delay_catcher_tmx import main as run_delay_catcher

app = Flask(__name__)

@app.route("/ping", methods=["GET"])
def ping():
    token = request.args.get("token")
    expected_token = os.getenv("KEEPALIVE_TOKEN")
    
    if expected_token and token != expected_token:
        print(f"❌ Unauthorized ping attempt with token: {token}")
        return "Unauthorized", 401

    print("📶 UptimeRobot ping received")
    return "pong", 200

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "message": "Delay Catcher TMX Webhook is running!"}), 200

@app.route("/webhook", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def webhook():
    # Log detailed information for all requests.
    import json
    print(f"🌐 Received {request.method} request to /webhook")
    print(f"📋 All Headers:")
    for key, value in request.headers.items():
        print(f"   {key}: {value}")
    
    print(f"🔍 Request Info:")
    print(f"   Remote Address: {request.environ.get('REMOTE_ADDR', 'Unknown')}")
    print(f"   User Agent: {request.headers.get('User-Agent', 'Unknown')}")
    print(f"   Content Type: {request.headers.get('Content-Type', 'None')}")
    print(f"   Content Length: {request.headers.get('Content-Length', 'None')}")
    
    # Log request body (if exist)
    if request.method in ['POST', 'PUT', 'PATCH']:
        try:
            if request.is_json:
                print(f"📄 JSON Body: {json.dumps(request.get_json(), indent=2)}")
            elif request.data:
                print(f"📄 Raw Body: {request.data}")
        except Exception as e:
            print(f"❌ Error reading body: {e}")
    
    print("=" * 60)
    
    # Asana webhook secret verification (use for registration handshake)
    if "X-Hook-Secret" in request.headers:
        secret = request.headers["X-Hook-Secret"]
        print(f"🔐 Detected X-Hook-Secret: {secret}")
        print(f"🤝 Returning handshake secret: {secret}")
        
        response = make_response(secret, 200)
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        response.headers['Content-Length'] = str(len(secret))
        response.headers['X-Hook-Secret'] = secret  # 🔑 Important: Asana may require you to echo this header back!
        return response
    
    # Handle GET request for webhook verification
    if request.method == "GET":
        print("✅ Handling GET request - returning webhook ready status")
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