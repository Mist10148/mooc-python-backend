# email_handler.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import uuid
import datetime

# Configuration for Email Sending (MUST BE UPDATED FOR PRODUCTION)
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SENDER_EMAIL = os.environ.get("MAIL_USERNAME", "glass418cloudy@gmail.com")

# ✅ FIX: Spaces removed from the hardcoded App Password. 
# Google App Passwords must be 16 characters with NO SPACES.
_raw_password = os.environ.get("MAIL_PASSWORD", "") 
SENDER_PASSWORD = _raw_password.replace(" ", "") # Safety strip

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

# --- HTML Template Generation (omitted for brevity) ---
def _create_reset_password_html_body(reset_link):
    # ... (HTML template code is unchanged) ...
    # 🎨 COLOR PALETTE (Teal-to-Blue Gradient Example)
    START_COLOR = "#1D4ED8"  # Blue-700 
    END_COLOR = "#0D9488"    # Teal-600
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
                <p style="margin-bottom: 20px; line-height: 1.6;">
                    Hello,
                </p>
                <p style="margin-bottom: 25px; line-height: 1.6;">
                    You recently requested to reset your password for your SilayLearn account. 
                    Click the button below to be taken to a secure page where you can create a 
                    <strong>new password</strong> and <strong>confirm the new password</strong>.
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
                    If you did not request a password reset, please ignore this email. Your password 
                    will remain the same. The reset link is valid for a short time only.
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
    """
    Sends a password reset link to the user.
    """
    reset_token = str(uuid.uuid4())
    print(f"DEBUG: Generated token {reset_token[:8]}... for {user_email}")
    
    reset_link = f"{FRONTEND_URL}/reset-password?token={reset_token}"
    subject = "Action Required: Reset Your SilayLearn Password"
    html_body = _create_reset_password_html_body(reset_link)
    
    plain_text_body = f"""
Hello,
You requested a password reset. Please click the link below:
{reset_link}
"""
    
    return _send_email(user_email, subject, plain_text_body, html_body), reset_token


def _send_email(to_email, subject, plain_text_body, html_body):
    """Internal function to send emails via SMTP, handling MIME Multipart."""
    
    # ⚠️ CHECK CONFIGURATION
    if SENDER_EMAIL == "your-email@gmail.com" or SENDER_PASSWORD == "your-app-password":
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! FATAL EMAIL CONFIG ERROR: SENDER_EMAIL or SENDER_PASSWORD uses default placeholder values. Update your .env or the default values in email_handler.py !!!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        return False, "Email configuration placeholders are still in use."

    try:
        # ✅ DEBUG PRINT: Attempting to send email with config details
        print(f"DEBUG: Attempting to connect to SMTP server: {SMTP_SERVER}:{SMTP_PORT} (Sender: {SENDER_EMAIL})")
        
        msg = MIMEMultipart('alternative')
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(plain_text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        
        # ✅ DEBUG PRINT: Attempting login
        print(f"DEBUG: Attempting SMTP login as {SENDER_EMAIL}...")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        
        text = msg.as_string()
        server.sendmail(SENDER_EMAIL, to_email, text)
        server.quit()
        
        # ✅ DEBUG PRINT: Success message
        print(f"SUCCESS: HTML Email sent to {to_email}")
        return True, "Email sent"
    except smtplib.SMTPAuthenticationError:
        print("ERROR: SMTP Authentication Failed.")
        print("Please check: 1. SENDER_EMAIL/SENDER_PASSWORD are correct. 2. If using Gmail, you MUST use an App Password, not your main password. 3. Less secure app access is disabled by Google now.")
        return False, "Authentication Error. Please use an App Password."
    except Exception as e:
        # ✅ DEBUG PRINT: Failure message
        print(f"ERROR: Failed to send email to {to_email}. Exception: {e}")
        return False, str(e)