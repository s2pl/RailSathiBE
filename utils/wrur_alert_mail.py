import os
import logging
from utils.email_utils import send_email_via_ms, send_plain_mail
from jinja2 import Template

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_wrur_alert_email_via_microservice(pnr_number, from_station, to_station, train_number, depot_name):
    """
    Send WRUR missing alert email via notification microservice.
    Uses MS template with Django fallback.
    """
    try:
        # Prepare context for MS template
        context = {
            "pnr_number": pnr_number or "N/A",
            "train_number": train_number or "N/A",
            "coach": "N/A",  # Not provided in this function
            "berth_no": "N/A",  # Not provided in this function
            "date_of_journey": f"{from_station} to {to_station}",
            "train_depot_name": depot_name or "N/A",
            "subject": f"WRUR Missing Alert for Train {train_number}, Depot {depot_name}"
        }
        
        # Try sending via MS first
        if not send_email_via_ms("contact@suvidhaen.com", "railsathi/war_room_missing_alert.txt", context):
            # Fallback to inline template
            env = os.getenv('ENV')
            if env == 'UAT':
                subject = f"UAT | WRUR Missing Alert for Train {train_number}, Depot {depot_name}"
            elif env == 'PROD':
                subject = f"WRUR Missing Alert for Train {train_number}, Depot {depot_name}"
            else:
                subject = f"LOCAL | WRUR Missing Alert for Train {train_number}, Depot {depot_name}"
            
            message = f"""
PNR Number: {pnr_number or 'N/A'}, travelling from {from_station or 'N/A'} to {to_station or 'N/A'} on Train Number {train_number or 'N/A'}, doesn't have a WRUR mapped.

Depot: {depot_name or 'N/A'}

Kindly verify the WRUR assignment to the given train depot.

This is an automated alert.

Regards,
Team RailSathi
"""
            
            send_plain_mail(
                subject=subject,
                message=message,
                from_=os.getenv("MAIL_FROM"),
                to=["contact@suvidhaen.com"]
            )
            logger.info("WRUR alert email sent via Django fallback")
        else:
            logger.info("WRUR alert email sent via MS")
        
        print("✅ Alert email sent to contact@suvidhaen.com")
    except Exception as e:
        logger.error(f"Failed to send WRUR alert email: {str(e)}")
