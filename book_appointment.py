from __future__ import print_function
import datetime
import os
import pickle
import base64
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import logging

# -----------------------------
# CONFIG
# -----------------------------
SCOPES_CAL = ['https://www.googleapis.com/auth/calendar']
SCOPES_GMAIL = ['https://www.googleapis.com/auth/gmail.send']

CREDENTIALS_FILE = 'credentials.json'  # OAuth JSON from Google Cloud
TOKEN_CAL = 'token_cal.pickle'
TOKEN_GMAIL = 'token_gmail.pickle'

# -----------------------------
# AUTHENTICATION
# -----------------------------
def authenticate_google(scopes, token_file):
    creds = None
    if os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, scopes)
            creds = flow.run_local_server(port=0)
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)
    return creds

# -----------------------------
# CREATE CALENDAR EVENT
# -----------------------------
def create_calendar_event(service, summary, description, start_time, duration_minutes, attendee_email, timezone):
    start_dt = datetime.datetime.strptime(start_time, "%Y-%m-%d %H:%M")
    end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)

    event = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': timezone,
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': timezone,
        },
        'attendees': [{'email': attendee_email}],
        'conferenceData': {
            'createRequest': {
                'requestId': f'meet-{start_dt.strftime("%Y%m%d%H%M")}',
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        },
    }

    created_event = service.events().insert(
        calendarId='primary',
        body=event,
        conferenceDataVersion=1,
        sendUpdates='all'
    ).execute()

    meet_link = created_event['conferenceData']['entryPoints'][0]['uri']
    return created_event, meet_link

# -----------------------------
# SEND EMAIL
# -----------------------------
def send_email(service, to, subject, message_text):
    message = MIMEText(message_text)
    message['to'] = to
    message['subject'] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    message_obj = {'raw': raw_message}
    return service.users().messages().send(userId='me', body=message_obj).execute()

# -----------------------------
# MAIN FUNCTION (call from agent)
# -----------------------------
def schedule_appointment(summary, description, start_time, attendee_email,duration=30, timezone="Asia/Kolkata"):
    # Authenticate
    creds_cal = authenticate_google(SCOPES_CAL, TOKEN_CAL)
    creds_gmail = authenticate_google(SCOPES_GMAIL, TOKEN_GMAIL)

    service_cal = build('calendar', 'v3', credentials=creds_cal)
    service_gmail = build('gmail', 'v1', credentials=creds_gmail)

    # Create event
    try:
        event, meet_link = create_calendar_event(
            service_cal, summary, description, start_time, duration, attendee_email, timezone
        )
    

        # Send email
        email_subject = f"Appointment Scheduled: {summary}"
        email_body = f"""Hello,
        Your appointment has been scheduled.

        Title: {summary}
        Description: {description}
        Date & Time: {start_time} ({timezone})
        Duration: {duration} minutes
        Google Meet link: {meet_link}

        See you then!"""

        send_email(service_gmail, attendee_email, email_subject, email_body)
    except Exception as e:
        logging.debug(f"Error creating calendar event: {e}")
    logging.info(f"Meeting schedule has been sent to {attendee_email}")
    return 

if __name__ == '__main__':
    # Example usage
    summary = "Project Discussion"
    description = "Discuss project requirements and next steps."
    start_time = "2024-07-01 15:00"  # YYYY-MM-DD HH:MM
    attendee_email = "bootcoding@gmail.com"
    schedule_appointment(summary, description, start_time, attendee_email,duration=30, timezone="Asia/Kolkata")