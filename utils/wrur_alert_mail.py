import os
import httpx
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMAIL_SVC_URL = os.getenv("EMAIL_SERVICE_URL", "https://railops-uat-api.biputri.com/notification_microservice/send-email")

async def send_wrur_alert_email_via_microservice(pnr_number, from_station, to_station, train_number, depot_name):
    email_payload = {
        "to": ["contact@suvidhaen.com"],
        "cc": [],
        "context": {
            "pnr_number": pnr_number or "N/A",
            "from_station": from_station or "N/A",
            "to_station": to_station or "N/A",
            "train_number": train_number or "N/A",
            "depot_name": depot_name or "N/A",
        },
        "template": """Subject: WRUR Missing Alert for Train {{ train_number }}, Depot {{ depot_name }}

PNR Number: {{ pnr_number }}, travelling from {{ from_station }} to {{ to_station }} on Train Number {{ train_number }}, doesn’t have a WRUR mapped.

Depot: {{ depot_name }}

"""
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                EMAIL_SVC_URL,
                json=email_payload,
                timeout=10.0
            )
            res.raise_for_status()
            print("✅ Alert email sent to contact@suvidhaen.com")
    except Exception as e:
        logger.error(f"Failed to send WRUR alert email via microservice: {str(e)}")
