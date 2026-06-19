import os
import ssl
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

def send_email_with_report():
    # 1. Read the credentials from the Hermes .env file
    env_path = Path(r"C:\Users\X\AppData\Local\hermes\.env")
    if not env_path.exists():
        print(f"Error: Hermes .env file not found at {env_path}")
        return False
        
    env_vars = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip('"').strip("'")
                
    sender_email = env_vars.get("EMAIL_ADDRESS")
    sender_password = env_vars.get("EMAIL_PASSWORD")
    smtp_host = env_vars.get("EMAIL_SMTP_HOST")
    smtp_port = env_vars.get("EMAIL_SMTP_PORT", "587")
    
    if not sender_email or not sender_password or not smtp_host:
        print("Error: Missing email credentials in Hermes .env file.")
        print(f"EMAIL_ADDRESS: {'set' if sender_email else 'missing'}")
        print(f"EMAIL_PASSWORD: {'set' if sender_password else 'missing'}")
        print(f"EMAIL_SMTP_HOST: {'set' if smtp_host else 'missing'}")
        return False
        
    recipient_email = "nnm23am036@nmamit.in"
    pdf_path = Path("D:/Technical/Programming/AI/Resumer/report.pdf").resolve()
    
    if not pdf_path.exists():
        print(f"Error: PDF report not found at {pdf_path}")
        return False
        
    # 2. Construct the message
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = "Project Technical Report: Resumer Agentic Resume Builder"
    
    body = """Dear Mohit,

Please find attached the Technical Project Report for the "Resumer" project, which is an Agentic Resume Builder & Intelligent Job Scraping Pipeline.

The report covers:
1. Executive Summary & Project Motivation
2. System Architecture & Workflows (including 3-phase scraping pipeline and multi-agent CrewAI tailoring crew)
3. SQLite Database Schema
4. Key Technical Implementation Highlights (Playwright PDF rendering with A4 auto-fit algorithm)
5. Setup and Commands Guide

This report was automatically compiled in LaTeX Computer Modern font and delivered using the Python SMTP automated pipeline.

Best regards,
Antigravity (AI Assistant)
"""
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    # 3. Attach the PDF
    print(f"Attaching PDF: {pdf_path.name}")
    try:
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={pdf_path.name}",
        )
        msg.attach(part)
    except Exception as e:
        print(f"Error attaching PDF file: {e}")
        return False
        
    # 4. Connect to SMTP server and send
    print(f"Connecting to SMTP server {smtp_host}:{smtp_port}...")
    try:
        port = int(smtp_port)
        if port == 465:
            # SSL
            server = smtplib.SMTP_SSL(smtp_host, port, timeout=30)
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()
        else:
            # STARTTLS (usually 587 or 25)
            server = smtplib.SMTP(smtp_host, port, timeout=30)
            server.starttls(context=ssl.create_default_context())
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()
            
        print("Email sent successfully!")
        return True
    except Exception as e:
        print(f"SMTP error occurred: {e}")
        return False

if __name__ == "__main__":
    send_email_with_report()
