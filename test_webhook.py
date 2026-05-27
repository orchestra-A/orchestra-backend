import urllib.request
import urllib.error
import hmac
import hashlib
import json

URL = "http://127.0.0.1:8000/webhook"
SECRET = "testsecret123"

def send_request(payload_bytes, headers):
    req = urllib.request.Request(URL, data=payload_bytes, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except urllib.error.URLError as e:
        return None, f"Failed to connect to the server: {e.reason}"

def test_webhook():
    print("--- Testing Webhook Signature Verification ---")
    
    payload = {"action": "opened", "issue": {"title": "Test issue"}}
    payload_bytes = json.dumps(payload).encode("utf-8")
    
    # 1. Test Without Signature
    print("\n1. Sending request WITHOUT signature...")
    status, body = send_request(payload_bytes, {"Content-Type": "application/json"})
    print(f"Status Code: {status}")
    print(f"Response: {body}")
    
    # 2. Test With Invalid Signature
    print("\n2. Sending request WITH INVALID signature...")
    headers_invalid = {
        "X-Hub-Signature-256": "sha256=invalid_hash",
        "X-GitHub-Event": "issues",
        "Content-Type": "application/json"
    }
    status, body = send_request(payload_bytes, headers_invalid)
    print(f"Status Code: {status}")
    print(f"Response: {body}")

    # 3. Test With Valid Signature
    print("\n3. Sending request WITH VALID signature...")
    mac = hmac.new(SECRET.encode(), payload_bytes, hashlib.sha256)
    valid_signature = "sha256=" + mac.hexdigest()
    
    headers_valid = {
        "X-Hub-Signature-256": valid_signature,
        "X-GitHub-Event": "issues",
        "Content-Type": "application/json"
    }
    status, body = send_request(payload_bytes, headers_valid)
    print(f"Status Code: {status}")
    print(f"Response: {body}")

if __name__ == "__main__":
    test_webhook()
