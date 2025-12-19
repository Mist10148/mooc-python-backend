# ai_handler.py
import os
import requests

# Gemini SDK (safe import)
try:
    from google import genai
except:
    genai = None

# Gemini configuration
# 🛑 CRITICAL: The previous key is failing. REPLACE this placeholder with a BRAND NEW, valid Gemini API Key.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
USE_SDK = True 

def parse_gemini_response(resp):
    """Safely extract the best output text from different possible Gemini SDK/REST formats."""
    if hasattr(resp, "text") and resp.text:
        return resp.text
    return str(resp)


def call_gemini_sdk(prompt):
    if genai is None:
        raise RuntimeError("google-genai SDK not installed")

    from google import genai as gemini_sdk
    client = gemini_sdk.Client(api_key=GEMINI_API_KEY)
    
    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return parse_gemini_response(resp)
    except Exception as e:
        # Fallback to REST call if SDK fails (e.g., specific environment issues)
        print(f"ERROR: Gemini SDK call failed. Falling back to REST call. Error: {e}")
        return call_gemini_rest(prompt)


def call_gemini_rest(prompt):
    url = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateText"
    body = {"prompt": {"text": prompt}, "temperature": 0.4, "maxOutputTokens": 800}

    try:
        # API key via query param
        resp = requests.post(url + f"?key={GEMINI_API_KEY}", json=body, timeout=30)
        
        # ✅ CRITICAL DEBUG STEP: Check for non-200 status codes immediately
        if resp.status_code != 200:
            data = resp.json()
            error_status = data.get('error', {}).get('status', 'N/A')
            error_message = data.get('error', {}).get('message', 'No message provided.')
            
            # Print the detailed error to the terminal
            print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print(f"!!! GEMINI API ERROR: HTTP Status Code {resp.status_code} !!!")
            print(f"!!! Status: {error_status}. Message: {error_message} !!!")
            if resp.status_code == 403 or resp.status_code == 400:
                 print("!!! ACTION REQUIRED: Your API Key is likely INVALID or REVOKED. !!!")
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")

            # Return a generic client-facing error message
            return "Error: unable to reach AI server."
            
        # If status code is 200, proceed to parse the response
        data = resp.json()

        if "candidates" in data:
            if 'content' in data["candidates"][0]:
                content = data["candidates"][0]['content']
                if 'parts' in content and content['parts']:
                    return content['parts'][0].get('text', str(content))
            return data["candidates"][0].get("output", str(data))
            
        return str(data)
        
    except requests.exceptions.RequestException as e:
        # This catches network errors (e.g., timeout, connection refused)
        print(f"\nFATAL NETWORK ERROR REACHING GEMINI: {e}\n")
        return "Network Error: Could not connect to the Gemini server endpoint."