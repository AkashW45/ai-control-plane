import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()


def send_execution_email(subject: str, body: str):

    sender = os.getenv("SMTP_SENDER")
    password = os.getenv("SMTP_PASSWORD")
    recipient = os.getenv("SMTP_RECIPIENT")

    if not sender or not password or not recipient:
        raise Exception("SMTP environment variables not configured properly.")

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)

    except Exception as e:
        raise Exception(f"Email sending failed: {str(e)}")