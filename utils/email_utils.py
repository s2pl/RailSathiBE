import logging
import asyncio
from fastapi_mail import FastMail, MessageSchema
from config.mail_config import conf, settings
from jinja2 import Template
from typing import Dict, List
import os
import sys
from database import get_db_connection, execute_query  # Fixed import
from datetime import datetime, date
import pytz
import json
from utils.notification_utils import send_passenger_complaint_notification_in_thread , send_passenger_complaint_push_and_in_app_in_thread
from utils.train_journey_utils import is_user_assigned_on_journey_date
import requests
from requests.exceptions import Timeout, RequestException

EMAIL_SENDER = conf.MAIL_FROM

os.makedirs("logs", exist_ok=True)

logger = logging.getLogger(__name__)

# Notification Microservice Configuration
NOTIFICATION_SERVICE_URL = settings.NOTIFICATION_SERVICE_URL

def send_email_via_ms(email: str, template_name: str, context: dict) -> bool:
    """
    Send email via notification microservice.
    Returns True if email sent successfully, False otherwise.
    """
    try:
        payload = {
            "email": email,
            "template_name": template_name,
            "context": context
        }
        
        response = requests.post(
            NOTIFICATION_SERVICE_URL,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            logging.info(f"Email sent via MS to {email} using template {template_name}")
            return True
        else:
            logging.error(f"MS returned status {response.status_code}: {response.text}")
            return False
            
    except Timeout:
        logging.error(f"Timeout calling notification microservice for {email}")
        return False
    except RequestException as e:
        logging.error(f"Error calling notification microservice: {repr(e)}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in send_email_via_ms: {repr(e)}")
        return False
logger.setLevel(logging.INFO)  # Capture everything at least INFO level

if not logger.handlers:
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_format)
    
    file_handler = logging.FileHandler("logs/db_errors.log")
    file_handler.setLevel(logging.ERROR)
    file_format = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    file_handler.setFormatter(file_format)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

def send_plain_mail(subject: str, message: str, from_: str, to: List[str], cc: List[str] = None):
    """Send plain text email with CC support"""
    try:
        # Filter valid emails
        valid_emails = [email for email in to if email and not email.startswith("noemail")]
        valid_cc_emails = [email for email in (cc or []) if email and not email.startswith("noemail")]
        
        if not valid_emails:
            logging.info("All emails were skipped - no valid recipients.")
            return True

        # Create email message - only include cc if there are valid CC emails
        email_params = {
            "subject": subject,
            "recipients": valid_emails,
            "body": message,
            "subtype": "plain"
        }
        
        # Only add cc parameter if there are valid CC emails
        if valid_cc_emails:
            email_params["cc"] = valid_cc_emails

        email = MessageSchema(**email_params)

        # Send email using FastMail
        fm = FastMail(conf)

        # Result container shared between threads
        result = {"success": False, "error": None}
        
        # Handle async call when event loop is already running
        import asyncio
        import threading
        
        def send_email_sync():
            # Create a new event loop in a separate thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                new_loop.run_until_complete(fm.send_message(email))
            finally:
                new_loop.close()
        
        # Run in a separate thread to avoid event loop conflicts
        thread = threading.Thread(target=send_email_sync)
        thread.start()
        thread.join()
        
        cc_info = f" with CC to: {', '.join(valid_cc_emails)}" if valid_cc_emails else ""
        logging.info(f"Email sent successfully to: {', '.join(valid_emails)}{cc_info}")
        return True
        
    except Exception as e:
        logging.exception(f"Error in send_plain_mail: {repr(e)}")
        return False

def send_passenger_complain_notifications(complain_details: Dict):
    """Send complaint email to war room users with CC to other users"""
    war_room_user_in_depot = []
    s2_admin_users = []
    railway_admin_users = []
    assigned_users_list = []
    assigned_cs_tokens = [] 
    
    #print(f"Complain Details for mail: {complain_details}")
    train_depo = complain_details.get('train_depo', '')
    #print(f"Train Depot: {train_depo}")
    train_no = str(complain_details.get('train_no', '')).strip()
    journey_start_date = complain_details.get('date_of_journey', '')
    
    #print(f"Train Name: {complain_details.get('train_name', 'Not provided')}")

    ist = pytz.timezone('Asia/Kolkata')
    complaint_created_at = datetime.now(ist).strftime("%d %b %Y, %H:%M")

    
    try:

        train_depot_name = train_depo

        # Step 2: Fetch war room users whose depots include the train depot
        war_room_user_query = f"""
            SELECT DISTINCT u.* 
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            JOIN user_onboarding_user_depots ud ON ud.user_id = u.id
            JOIN station_depot d ON d.depot_id = ud.depot_id
            WHERE ut.name IN ('war room user', 'war room user railsathi')
            AND d.depot_code = '{train_depot_name}'
            AND u.user_status = 'enabled'
        """
        conn = get_db_connection()
        war_room_user_in_depot = execute_query(conn, war_room_user_query)
        conn.close()

        # S2 Admin users query
        s2_admin_query = f"""
            SELECT DISTINCT u.* 
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            JOIN user_onboarding_user_depots ud ON ud.user_id = u.id
            JOIN station_depot d ON d.depot_id = ud.depot_id
            WHERE ut.name = 's2 admin'
            AND d.depot_code = '{train_depot_name}'
            AND u.user_status = 'enabled'
        """
        conn = get_db_connection()
        s2_admin_users = execute_query(conn, s2_admin_query)
        conn.close()

        # Railway admin users query
        railway_admin_query = f"""
            SELECT DISTINCT u.* 
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            JOIN user_onboarding_user_depots ud ON ud.user_id = u.id
            JOIN station_depot d ON d.depot_id = ud.depot_id
            WHERE ut.name IN ('railway admin', 'railway officer')
            AND d.depot_code = '{train_depot_name}'
            AND u.user_status = 'enabled'
        """
        conn = get_db_connection()
        railway_admin_users = execute_query(conn, railway_admin_query)
        conn.close()

        # Train access users query (no depot filtering needed here)
        assigned_users_query = """
            SELECT u.email, u.id, u.first_name, u.last_name, u.fcm_token, u.fcm_token_coachsathi, ta.train_details
            FROM user_onboarding_user u
            JOIN trains_trainaccess ta ON ta.user_id = u.id
            WHERE ta.train_details IS NOT NULL 
            AND ta.train_details != '{}'
            AND ta.train_details != 'null'
            AND u.user_status = 'enabled'
        """
        conn = get_db_connection()
        assigned_users_raw = execute_query(conn, assigned_users_query)
        conn.close()

        # Get train number and complaint date for filtering
        train_no = str(complain_details.get('train_no', '')).strip()

        # Get complaint date and current time
        created_at_raw = date.today().strftime('%Y-%m-%d')
        complaint_date_str = created_at_raw  # Keep as string in YYYY-MM-DD format
        complaint_validation_time = datetime.now()  # Current datetime for time comparison

        logger.info("2. Complaint Date: " + str(complaint_date_str))
        logger.info("3. Complaint Validation Time: " + str(complaint_validation_time))

        if complaint_date_str and train_no:
            for user in assigned_users_raw:
                try:
                    train_details_str = user.get('train_details', '{}')
                    
                    # Handle case where train_details might be a string or already parsed
                    if isinstance(train_details_str, str):
                        train_details = json.loads(train_details_str)
                    else:
                        train_details = train_details_str
                    
                    # Check if the train number exists in train_details
                    if train_no in train_details:
                        for access in train_details[train_no]:
                            try:
                                origin_date_str = access.get('origin_date', '')
                                
                                if not origin_date_str:
                                    continue
                                
                                # Validate origin_date format
                                datetime.strptime(origin_date_str, "%Y-%m-%d")
                                
                                # Use the multi-day journey utility function
                                is_assigned = is_user_assigned_on_journey_date(
                                    origin_date_str=origin_date_str,
                                    pnr_journey_date_str=complaint_date_str,
                                    pnr_validation_time=complaint_validation_time,
                                    train_no=train_no
                                )
                                
                                if is_assigned:
                                    logger.info(f"✓ Date criteria matched for user {user.get('email')}, now checking coach assignment...")
                                    
                                    # Get coach_numbers from this entry
                                    coach_numbers = access.get("coach_numbers", [])
                                    logger.info(f"Assigned coach_numbers: {coach_numbers}")
                                    
                                    # Get complaint coach
                                    complaint_coach = complain_details.get("coach", "")
                                    logger.info(f"Complaint coach: {complaint_coach}")
                                    
                                    # Check if complaint coach matches assigned coaches
                                    coach_match = False
                                    if coach_numbers and complaint_coach:
                                        coach_match = complaint_coach in coach_numbers
                                    
                                    if coach_match:
                                        logger.info(f"✓✓✓ COACH MATCHED! User {user.get('email')} IS assigned.")
                                        assigned_users_list.append(user)
                                        
                                        # Also collect CoachSathi token separately for aggregation
                                        if user.get("fcm_token_coachsathi"):
                                            assigned_cs_tokens.append(user.get("fcm_token_coachsathi"))
                                        
                                        break  # Only need one match per user
                                    else:
                                        logger.info(f"✗ Coach criteria not met - complaint coach '{complaint_coach}' not in assigned coaches {coach_numbers}")
                                    
                            except (ValueError, TypeError) as date_error:
                                logging.warning(f"Date parsing error for user {user.get('id')}: {date_error}")
                                continue
                                
                except (json.JSONDecodeError, TypeError) as json_error:
                    logging.warning(f"JSON parsing error for user {user.get('id')}: {json_error}")
                    continue


        # Combine all users and collect unique emails
        all_users_to_mail = war_room_user_in_depot + s2_admin_users + railway_admin_users + assigned_users_list

        print(f"Total users to mail: {len(all_users_to_mail)}")

        # for user in all_users_to_mail:
        #     print("User:", user.get("email"), "| FCM Token:", user.get("fcm_token"))

        # Extract valid FCM tokens
        railsathi_tokens = [user.get("fcm_token") for user in all_users_to_mail if user.get("fcm_token")]
        railsathi_tokens = list(set(railsathi_tokens))  # remove duplicates

        coachsathi_tokens = [user.get("fcm_token_coachsathi") for user in all_users_to_mail if user.get("fcm_token_coachsathi")]
        coachsathi_tokens.extend(assigned_cs_tokens) 
        coachsathi_tokens = list(set(coachsathi_tokens))  # remove duplicates

        fcm_tokens = {
            "railsathi": railsathi_tokens,
            "coachsathi": coachsathi_tokens
        }
        # Using existing complaint data to trigger push notification for war room / admin users.
        try:
            if fcm_tokens["railsathi"] or fcm_tokens["coachsathi"]:
                # Build a complaint dict compatible with notification util expectations
                complaint_for_notification = {
                    "complain_id": complain_details.get('complain_id') or complain_details.get('complaint_id'),
                    "passenger_name": complain_details.get('passenger_name', ''),
                    "passenger_phone": complain_details.get('user_phone_number') or complain_details.get('passenger_phone', ''),
                    "train_no": complain_details.get('train_no', ''),
                    "train_name": complain_details.get('train_name', ''),
                    "coach": complain_details.get('coach', ''),
                    "berth": complain_details.get('berth', ''),
                    "pnr": complain_details.get('pnr', 'PNR not provided by passenger'),
                    "description": complain_details.get('description', ''),
                    "train_depo": complain_details.get('train_depo', ''),
                    "priority": complain_details.get('priority', 'normal'),
                    "date_of_journey": journey_start_date,
                    "created_at": complaint_created_at,  # already formatted as %d %b %Y, %H:%M
                }
                # Dispatch push notification in a background thread (non-blocking)
                logging.debug(f"[Push][Build] Complaint notification payload: {json.dumps(complaint_for_notification, indent=2, ensure_ascii=False)}")
                print("[DEBUG] Push Notification Payload =>", complaint_for_notification)
                if railsathi_tokens:
                    send_passenger_complaint_push_and_in_app_in_thread(
                        railsathi_tokens, 
                        complaint_for_notification,
                        product_name="railops"
                    )
                    logging.info(f"Push notification thread started for RailSathi complaint {complaint_for_notification.get('complain_id')}")

                if coachsathi_tokens:
                    send_passenger_complaint_push_and_in_app_in_thread(
                        coachsathi_tokens, 
                        complaint_for_notification,
                        product_name="coachsathi"
                    )
                    logging.info(f"Push notification thread started for CoachSathi complaint {complaint_for_notification.get('complain_id')}")
                    
            else:
                logging.info(f"No FCM tokens available for complaint {complain_details.get('complain_id')}")
        except Exception as push_err:
            logging.error(f"Error sending push notification for complaint {complain_details.get('complain_id')}: {push_err}")

     
    except Exception as e:
        logging.error(f"Error fetching users: {e}")

    try:
        env = os.getenv('ENV')
        # Prepare email content
        if env == 'UAT':
            subject = f"UAT | New Passenger Complaint Submitted - for Train: {complain_details['train_no']}(Commencement Date: {journey_start_date})"
        elif env == 'PROD':
            subject = f"New Passenger Complaint Submitted - for Train: {complain_details['train_no']}(Commencement Date: {journey_start_date})"
        else:
            subject = f"LOCAL | New Passenger Complaint Submitted - for Train: {complain_details['train_no']}(Commencement Date: {journey_start_date})"
            
        pnr_value = complain_details.get('pnr', 'PNR not provided by passenger')

        
        context = {
            "user_phone_number": complain_details.get('user_phone_number', ''),
            "passenger_name": complain_details.get('passenger_name', ''),
            "train_no": complain_details.get('train_no', ''),
            "train_name": complain_details.get('train_name', ''),
            "pnr": pnr_value,
            "berth": complain_details.get('berth', ''),
            "coach": complain_details.get('coach', ''),
            "complain_id": complain_details.get('complain_id', ''),
            "created_at": complaint_created_at,
            "description": complain_details.get('description', ''),
            "train_depo": complain_details.get('train_depo', ''),
            "complaint_date": complaint_date_str,
            "start_date_of_journey": journey_start_date,
            'site_name': 'RailSathi',
        }

        # Load and render template
        template_path = os.path.join("templates", "complaint_creation_email_template.txt")
        
        if not os.path.exists(template_path):
            # Fallback to inline template if file doesn't exist
            template_content = """
                Passenger Complaint Submitted

                A new passenger complaint has been received.

                Complaint ID   : {{ complain_id }}
                Submitted At  : {{ created_at }}

                Passenger Info:
                ---------------
                Name           : {{ passenger_name }}
                Phone Number   : {{ user_phone_number }}

                Travel Details:
                ---------------
                Train Number   : {{ train_no }}
                Train Name     : {{ train_name }}
                Coach          : {{ coach }}
                Berth Number   : {{ berth }}
                PNR            : {{ pnr }}

                Complaint Details:
                ------------------
                Description    : {{ description }}

                Train Depot    : {{ train_depo }}
                
                Please take necessary action at the earliest.

                This is an automated notification. Please do not reply to this email.

                Regards,  
                Team RailSathi
            """
        else:
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
        
        template = Template(template_content)
        message = template.render(context)
        
        # Collect all unique email addresses
        all_emails = []
        for user in all_users_to_mail:
            email = user.get('email', '')
            if email and not email.startswith("noemail") and '@' in email:
                all_emails.append(email)
        
        # Remove duplicates while preserving order
        unique_emails = list(dict.fromkeys(all_emails))
        #unique_emails = ["harshnmishra01@gmail.com","harshnmishra.s2@gmail.com"]
        
        
        if not unique_emails:
            logging.info(f"No users found for depot {train_depo} and train {train_no} in complaint {complain_details['complain_id']}")
            return {"status": "success", "message": "No users found for this depot and train"}
        
        # Send single email with first recipient as TO and rest as CC
        primary_recipient = [unique_emails[0]]
        cc_recipients = unique_emails[1:] if len(unique_emails) > 1 else []
        
        # Add subject to context for MS template
        context['subject'] = subject
        
        try:
            # Try sending via notification microservice first
            if not send_email_via_ms(primary_recipient[0], "railsathi/complaint_creation.txt", context):
                # Fallback to Django if MS fails
                template_path = os.path.join("templates", "complaint_creation_email_template.txt")
                
                if not os.path.exists(template_path):
                    template_content = """
                Passenger Complaint Submitted

                A new passenger complaint has been received.

                Complaint ID   : {{ complain_id }}
                Submitted At  : {{ created_at }}

                Passenger Info:
                ---------------
                Name           : {{ passenger_name }}
                Phone Number   : {{ user_phone_number }}

                Travel Details:
                ---------------
                Train Number   : {{ train_no }}
                Train Name     : {{ train_name }}
                Coach          : {{ coach }}
                Berth Number   : {{ berth }}
                PNR            : {{ pnr }}

                Complaint Details:
                ------------------
                Description    : {{ description }}

                Train Depot    : {{ train_depo }}
                
                Please take necessary action at the earliest.

                This is an automated notification. Please do not reply to this email.

                Regards,  
                Team RailSathi
            """
                else:
                    with open(template_path, 'r', encoding='utf-8') as f:
                        template_content = f.read()
                
                template = Template(template_content)
                message = template.render(context)
                
                success = send_plain_mail(subject, message, EMAIL_SENDER, primary_recipient, cc_recipients)
                logging.info("Email sent via Django fallback")
            else:
                success = True
                logging.info("Email sent via MS")
            if success:
                logging.info(f"Email sent for complaint {complain_details['complain_id']} to {len(unique_emails)} recipients")
                logging.info(f"Primary recipient: {primary_recipient[0]}")
                if cc_recipients:
                    logging.info(f"CC recipients: {', '.join(cc_recipients)}")
                return {"status": "success", "message": f"Email sent to {len(unique_emails)} users"}
            else:
                logging.error(f"Failed to send email for complaint {complain_details['complain_id']}")
                return {"status": "error", "message": "Failed to send email"}
        except Exception as e:
            logging.error(f"Error sending email for complaint {complain_details['complain_id']}: {e}")
            return {"status": "error", "message": str(e)}
        
    except Exception as e:
        logging.error(f"Error in send_passenger_complain_notifications: {e}")
        return {"status": "error", "message": str(e)}
    
    
def execute_sql_query(sql_query: str):
    """Execute a SELECT query safely"""
    if not sql_query.strip().lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed")

    conn = get_db_connection()
    try:
        results = execute_query(conn, sql_query)
        return results
    finally:
        conn.close()