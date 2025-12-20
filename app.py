# app.py

import os
import uuid  # For generating unique reset tokens
import datetime # For setting token expiration time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, render_template, request, jsonify
import mysql.connector
import requests
from flask_cors import CORS
import bcrypt # For secure password hashing and checking

# Load .env file for local development (if library exists)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # In production (Docker), env vars are set by the server

# Gemini SDK (safe import)
try:
    from google import genai
except ImportError:
    genai = None

app = Flask(__name__, static_folder="static", template_folder="templates")

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                "https://mooc-frontend-myqa.onrender.com"
            ]
        }
    },
    supports_credentials=False
)



# --------------------------
# Database configuration (SECURE)
# --------------------------
DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASS"),
    "database": os.environ.get("DB_NAME"),
    "port": int(os.environ.get("DB_PORT", 3306)),
    # Aiven requires SSL. 'ssl_disabled=False' is safer.
    "ssl_disabled": False 
}

# --------------------------
# Gemini configuration (SECURE)
# --------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
USE_SDK = True  # switch to False to use REST

# --------------------------
# Email Configuration (SECURE)
# --------------------------
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SENDER_EMAIL = os.environ.get("MAIL_USERNAME")
# Remove spaces if they exist in the env var
_raw_password = os.environ.get("MAIL_PASSWORD", "")
SENDER_PASSWORD = _raw_password.replace(" ", "") 

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:8080")

# NEW CONSTANT
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
    if hasattr(resp, "text") and resp.text: return resp.text
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
# Email handler functions
# --------------------------
def _create_reset_password_html_body(reset_link): 
    START_COLOR = "#1D4ED8"  
    END_COLOR = "#0D9488"    
    ACCENT_COLOR = "#0D9488" 
    BG_COLOR = "#f7f7f7"
    CARD_BG = "#ffffff"
    TEXT_COLOR = "#333333"

    GRADIENT_STYLE = f"""
        background-color: {START_COLOR}; 
        background-image: linear-gradient(to right, {START_COLOR}, {END_COLOR});
        color: white; 
        padding: 24px 20px; 
        text-align: center;
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Password Reset</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: {BG_COLOR}; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: {CARD_BG}; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); overflow: hidden;">
            
            <div style="{GRADIENT_STYLE}">
                <h1 style="margin: 0; font-size: 24px; font-weight: bold;">
                    Silay<span style="color: {CARD_BG};">Learn</span>
                </h1>
            </div>

            <div style="padding: 30px 40px; color: {TEXT_COLOR};">
                <h2 style="font-size: 20px; color: #1f2937; margin-top: 0; margin-bottom: 20px;">
                    Reset Your Password
                </h2>
                <p style="margin-bottom: 25px; line-height: 1.6;">
                    Click the button below to be taken to a secure page to set a new password.
                </p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" 
                       target="_blank" 
                       style="display: inline-block; padding: 12px 25px; background-color: {ACCENT_COLOR}; 
                              color: {CARD_BG}; text-decoration: none; border-radius: 8px; 
                              font-weight: bold; font-size: 16px; box-shadow: 0 4px 8px rgba(13, 148, 136, 0.3);">
                        Set New Password
                    </a>
                </div>

                <p style="font-size: 14px; margin-top: 30px; border-top: 1px solid #eeeeee; padding-top: 15px; color: #6b7280;">
                    If you did not request a password reset, please ignore this email.
                </p>
            </div>

            <div style="background-color: {BG_COLOR}; padding: 15px; text-align: center; font-size: 12px; color: #9ca3af;">
                &copy; {datetime.date.today().year} SilayLearn. All rights reserved.
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_reset_email(user_email): 
    reset_token = str(uuid.uuid4())
    reset_link = f"{FRONTEND_URL}/reset-password?token={reset_token}"
    subject = "Action Required: Reset Your SilayLearn Password"
    html_body = _create_reset_password_html_body(reset_link)
    plain_text_body = f"Hello,\nYou requested a password reset. Please click the link below:\n{reset_link}"
    
    success, msg = _send_email(user_email, subject, plain_text_body, html_body)
    
    if success:
        return True, reset_token 
    else:
        return False, msg


def _send_email(to_email, subject, plain_text_body, html_body): 
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(plain_text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        
        text = msg.as_string()
        server.sendmail(SENDER_EMAIL, to_email, text)
        server.quit()
        
        return True, "Email sent"
        
    except smtplib.SMTPAuthenticationError:
        print("\nFATAL ERROR: SMTP Authentication Failed.")
        return False, "Authentication Error. Check config."
    except Exception as e:
        print(f"FATAL ERROR: Failed to send email to {to_email}. Exception: {e}")
        return False, str(e)


# --------------------------
# Routes
# --------------------------
@app.route("/")
def index(): 
    return jsonify({"message": "Python Backend is Running"}), 200

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
    
    if not user_id: return jsonify({"reply": "Error: Invalid user_id provided."}), 400
    try: user_id = int(user_id)
    except: return jsonify({"reply": "Error: user_id must be an integer."}), 400

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

# ✅ FIX 3: Removed manual OPTIONS check (handled by after_request)
@app.route("/api/auth/forgot-password", methods=["POST", "OPTIONS"])
def forgot_password(): 
    data = request.json
    email = data.get("email")

    if not email:
        return jsonify({"message": "Email is required"}), 400
    
    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        user_record = cursor.fetchone()
        if not user_record:
            return jsonify({"message": "If an account exists, a password reset link has been sent."}), 200

        user_id = user_record[0]
        
        success, msg_or_token = send_reset_email(email)
        
        if not success:
            return jsonify({"message": "Failed to send email.", "error": msg_or_token}), 500

        reset_token = msg_or_token 

        expires_at = datetime.datetime.now() + datetime.timedelta(hours=1)
        
        cursor.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
            (user_id, reset_token, expires_at)
        )
        db.commit()

        return jsonify({"message": "Password reset link sent. Check your inbox."}), 200

    except mysql.connector.Error as err:
        db.rollback()
        print(f"ERROR: Database error: {err.msg}")
        return jsonify({"message": "Failed to generate reset link."}), 500
    finally:
        cursor.close()
        db.close()


# ✅ FIX 4: Removed manual OPTIONS check (handled by after_request)
@app.route("/api/auth/reset-password", methods=["POST", "OPTIONS"])
def reset_password(): 

    data = request.json
    token = data.get("token")
    new_password = data.get("newPassword")
    
    if not all([token, new_password]):
        return jsonify({"message": "Token and new password are required."}), 400
    
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({"message": f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    try:
        cursor.execute(
            "SELECT user_id FROM password_reset_tokens WHERE token=%s AND expires_at > NOW()",
            (token,)
        )
        token_record = cursor.fetchone()

        if not token_record:
            return jsonify({"message": "Invalid or expired password reset link."}), 401

        user_id = token_record['user_id']
        
        hashed_password = bcrypt.hashpw(
            new_password.encode('utf-8'), 
            bcrypt.gensalt()
        ).decode('utf-8')

        db.autocommit = False
        cursor.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (hashed_password, user_id)
        )

        cursor.execute(
            "DELETE FROM password_reset_tokens WHERE token = %s",
            (token,)
        )
        
        db.commit()
        db.autocommit = True

        return jsonify({"message": "Password updated successfully."}), 200

    except mysql.connector.Error as err:
        db.rollback()
        print(f"ERROR: Database error: {err.msg}")
        return jsonify({"message": f"Server error: {err.msg}"}), 500
    finally:
        cursor.close()
        db.close()

# ✅ FIX 5: Removed manual OPTIONS check (handled by after_request)
@app.route("/api/auth/delete", methods=["DELETE", "OPTIONS"])
def delete_account():

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
        cursor.execute("DELETE FROM users WHERE id=%s", (db_id,))
        db.commit() 
        db.autocommit = True
        
        return jsonify({"message": "Account deleted successfully."}), 200

    except mysql.connector.Error as err:
        if db: db.rollback()
        return jsonify({"message": f"Database error: {err.msg}"}), 500
    except ValueError:
        return jsonify({"message": "Invalid user ID format."}), 400
    finally:
        if cursor: cursor.close()
        if db: db.close()

if __name__ == "__main__":
    # Gunicorn uses the PORT env var; locally we default to 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port)