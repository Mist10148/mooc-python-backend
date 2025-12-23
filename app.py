# app.py - SIMPLIFIED VERSION WITHOUT EMAIL AUTOMATION
# Forgot/Reset Password endpoints removed - now handled by PHP

import os
import datetime

from flask import Flask, request, jsonify
import mysql.connector
import requests
import bcrypt

# Load .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Gemini SDK (safe import)
try:
    from google import genai
except ImportError:
    genai = None

app = Flask(__name__, static_folder="static", template_folder="templates")

# ✅ SIMPLIFIED CORS - NO LIBRARY NEEDED
@app.after_request
def after_request(response):
    # Allow requests from your frontend
    response.headers['Access-Control-Allow-Origin'] = 'https://mooc-frontend-myqa.onrender.com'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# ✅ Handle OPTIONS requests (preflight)
@app.before_request
def handle_options():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers['Access-Control-Allow-Origin'] = 'https://mooc-frontend-myqa.onrender.com'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response, 200

# --------------------------
# Database configuration (SECURE)
# --------------------------
DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASS"),
    "database": os.environ.get("DB_NAME"),
    "port": int(os.environ.get("DB_PORT", 3306)),
    "ssl_disabled": False 
}

# --------------------------
# Gemini configuration (SECURE)
# --------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
USE_SDK = True

MIN_PASSWORD_LENGTH = 6

# --------------------------
# DB helper functions
# --------------------------
def get_db(): 
    """Establishes a connection to the MySQL database."""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as err:
        print(f"Database Connection Error: {err}")
        raise

def save_message(user_id, role, message): 
    """Saves a chat message."""
    db = None
    cursor = None
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO chat_history (user_id, role, message) VALUES (%s, %s, %s)",
            (user_id, role, message)
        )
        db.commit()
    except mysql.connector.Error as err:
        print(f"ERROR saving message: {err.msg}")
    finally:
        if cursor: cursor.close()
        if db: db.close()

def load_chat_summary(user_id): 
    """Retrieves history for the specific user_id to provide context to the AI."""
    db = None
    cursor = None
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT role, message FROM chat_history WHERE user_id=%s ORDER BY id DESC LIMIT 10",
            (user_id,)
        )
        rows = cursor.fetchall()
        
        if not rows:
            return "No previous conversation."

        summary = []
        for role, msg in reversed(rows):
            short = msg[:120].replace("\n", " ")
            summary.append(f"{role}: {short}")

        return "\n".join(summary)
    except Exception as e:
        print(f"Error loading summary: {e}")
        return "Error loading context."
    finally:
        if cursor: cursor.close()
        if db: db.close()

def get_chat_history(user_id): 
    """
    Retrieves the full chat history for a user, structured for API response.
    """
    db = None
    cursor = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True) 
        
        cursor.execute(
            "SELECT id, role, message, created_at FROM chat_history WHERE user_id=%s ORDER BY id ASC",
            (user_id,)
        )
        history = cursor.fetchall()
        
        for item in history:
            if 'created_at' in item and hasattr(item['created_at'], 'isoformat'):
                item['created_at'] = item['created_at'].isoformat()
            
        return history
    except Exception as e:
        print(f"Error getting history: {e}")
        raise
    finally:
        if cursor: cursor.close()
        if db: db.close()

# --------------------------
# Gemini handler functions
# --------------------------
def parse_gemini_response(resp): 
    """Safely extract the best output text from different possible Gemini SDK/REST formats."""
    if hasattr(resp, "text") and resp.text: 
        return resp.text
    return str(resp)

def call_gemini_sdk(prompt): 
    """Tries the Gemini SDK, falls back to REST call on failure."""
    if genai is None:
        return "SDK not installed. Falling back to REST call..." + call_gemini_rest(prompt)

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return parse_gemini_response(resp)
    except Exception as e:
        print(f"ERROR: Gemini SDK call failed. Falling back to REST call. Error: {e}")
        return call_gemini_rest(prompt)

def call_gemini_rest(prompt): 
    """Calls Gemini API using REST for maximum compatibility and debugging."""
    url = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateText"
    body = {"prompt": {"text": prompt}, "temperature": 0.4, "maxOutputTokens": 800}

    try:
        resp = requests.post(url + f"?key={GEMINI_API_KEY}", json=body, timeout=30)
        
        if resp.status_code != 200:
            data = resp.json()
            error_message = data.get('error', {}).get('message', 'No message provided.')
            print(f"!!! GEMINI API ERROR: {resp.status_code} - {error_message}")
            return "Error: unable to reach AI server."
            
        data = resp.json()
        if "candidates" in data:
            if 'content' in data["candidates"][0]:
                content = data["candidates"][0]['content']
                if 'parts' in content and content['parts']:
                    return content['parts'][0].get('text', str(content))
            return data["candidates"][0].get("output", str(data))
            
        return str(data)
        
    except requests.exceptions.RequestException as e:
        print(f"\nFATAL NETWORK ERROR REACHING GEMINI: {e}\n")
        return "Network Error: Could not connect to the Gemini server endpoint."

# --------------------------
# Routes
# --------------------------
@app.route("/")
def index(): 
    return jsonify({"message": "Python Backend is Running", "status": "ok"}), 200

@app.route("/health")
def health(): 
    return jsonify({"status": "healthy"}), 200

# --- Chat Routes ---

@app.route("/api/chat/history/<int:user_id>", methods=["GET"])
def chat_history_route(user_id): 
    try:
        history = get_chat_history(user_id)
        return jsonify(history), 200
    except Exception as e:
        print(f"ERROR fetching chat history for user {user_id}: {e}")
        return jsonify({"message": "Failed to retrieve chat history."}), 500

@app.route("/chat", methods=["POST"])
def chat(): 
    data = request.json
    user_id = data.get("user_id") or data.get("userId") 
    user_msg = data.get("message", "")
    lesson_title = data.get("lesson_title", "MOOC Lesson")
    language = data.get("language", "en")
    
    if not user_id: 
        return jsonify({"reply": "Error: Invalid user_id provided."}), 400
    try: 
        user_id = int(user_id)
    except: 
        return jsonify({"reply": "Error: user_id must be an integer."}), 400

    save_message(user_id, "user", user_msg)
    summary = load_chat_summary(user_id)

    system_prompt = f"""
You are the MOOC Lesson AI Assistant integrated into an educational platform.
Lesson: {lesson_title}

--- Student Conversation Summary ---
{summary}

--- Role ---
You help Filipino MOOC students by:
- Answering simply and accurately
- Giving local Ilonggo examples
- Providing Filipino/Hiligaynon translations when asked
- NEVER including sensitive data

User says:
{user_msg}

Preferred language: {language}
"""

    try:
        if USE_SDK:
            reply = call_gemini_sdk(system_prompt)
        else:
            reply = call_gemini_rest(system_prompt)
    except Exception as e:
        reply = f"Error contacting AI service: {str(e)}"

    save_message(user_id, "assistant", reply)
    return jsonify({"reply": reply})

# --- Authentication and User Management Routes ---
# NOTE: Forgot Password and Reset Password are now handled by PHP

@app.route("/api/auth/delete", methods=["DELETE", "OPTIONS"])
def delete_account():
    if request.method == "OPTIONS":
        return jsonify({"message": "OK"}), 200

    data = request.get_json()
    
    db_id_from_request = data.get("dbId")
    email = data.get("email")
    password = data.get("password")

    if not all([db_id_from_request, email, password]):
        return jsonify({"message": "Missing required fields."}), 400

    db = None
    cursor = None
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True) 
        db_id = int(db_id_from_request) 

        cursor.execute("SELECT password FROM users WHERE id=%s AND email=%s", (db_id, email))
        user_record = cursor.fetchone()

        if not user_record:
            return jsonify({"message": "User not found or ID/email mismatch."}), 404
        
        stored_hash = user_record['password']
        
        try:
            hashed_password_bytes = stored_hash.encode('utf-8')
            if not bcrypt.checkpw(password.encode('utf-8'), hashed_password_bytes): 
                return jsonify({"message": "Invalid password confirmation."}), 401
        except Exception as e:
            print(f"ERROR: Bcrypt check failed: {e}")
            return jsonify({"message": "Invalid password confirmation (hashing error)."}), 401
            
        db.autocommit = False 
        cursor.execute("DELETE FROM chat_history WHERE user_id=%s", (db_id,))
        cursor.execute("DELETE FROM password_reset_tokens WHERE user_id=%s", (db_id,))
        cursor.execute("DELETE FROM users WHERE id=%s", (db_id,))
        db.commit() 
        db.autocommit = True
        
        return jsonify({"message": "Account deleted successfully."}), 200

    except mysql.connector.Error as err:
        if db: 
            db.rollback()
        return jsonify({"message": f"Database error: {err.msg}"}), 500
    except ValueError:
        return jsonify({"message": "Invalid user ID format."}), 400
    finally:
        if cursor: 
            cursor.close()
        if db: 
            db.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask app on port {port}...")
    print("NOTE: Forgot/Reset Password endpoints are now handled by PHP backend")
    app.run(debug=False, host='0.0.0.0', port=port)