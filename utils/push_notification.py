import os
import logging
from pyfcm import FCMNotification

# Base directory of the repo
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Path to service account JSON file
service_account_path = os.path.join(BASE_DIR, "fcm_cred_sample.json")

push_service = None
try:
    push_service = FCMNotification(service_account_file=service_account_path)
except Exception as e:
    logging.error(f"Failed to initialize FCM push service: {e}")
    push_service = None


def send_push_notification(token, title, body, data=None):
    if not push_service:
        logging.error("Push service not initialized. Notification not sent.")
        return None

    if not token:
        logging.warning("Empty or missing FCM token. Skipping push notification.")
        return None

    try:
        # Send notification via Firebase
        result = push_service.notify_single_device(
            registration_id=token,
            message_title=title,
            message_body=body,
            data_message=data or {}
        )
        logging.info(f"Push notification sent. Response: {result}")
        return result
    
    except Exception as e:
        logging.error(f"Failed to send push notification: {e}")
        return None