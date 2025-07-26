import logging
import asyncio
from fastapi_mail import FastMail, MessageSchema
from mail_config import conf
from jinja2 import Template
from typing import Dict, List
import os
from database import get_db_connection, execute_query  # Fixed import
from datetime import datetime
import pytz
import json

EMAIL_SENDER = conf.MAIL_FROM

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


def send_passenger_complain_email(complain_details: Dict):
    """Send complaint email to war room users with CC to other users"""
    war_room_user_in_depot = []
    s2_admin_users = []
    railway_admin_users = []
    assigned_users_list = []
    
    train_depo = complain_details.get('train_depot', '')
    train_no = str(complain_details.get('train_no', '')).strip()
    complaint_date = complain_details.get('created_at', '') 
    journey_start_date = complain_details.get('date_of_journey', '')

    ist = pytz.timezone('Asia/Kolkata')
    complaint_created_at = datetime.now(ist).strftime("%d %b %Y, %H:%M")

    
    try:
        # Step 1: Get Depot for the train number
        get_depot_query = f"""
            SELECT "Depot" FROM trains_traindetails 
            WHERE train_no = '{train_no}' LIMIT 1
        """
        conn = get_db_connection()
        depot_result = execute_query(conn, get_depot_query)
        conn.close()

        train_depot_name = depot_result[0]['Depot'] if depot_result else ''

        # Step 2: Fetch war room users whose `depo` matches the train depot
        war_room_user_query = f"""
            SELECT u.* 
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            WHERE ut.name IN ('war room user', 'war room user railsathi') AND u.depo LIKE '%{train_depot_name}%'
        """
        conn = get_db_connection()
        war_room_user_in_depot = execute_query(conn, war_room_user_query)
        conn.close()  
            
        s2_admin_query = f"""
            SELECT u.* 
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            WHERE ut.name = 's2 admin' AND u.depo LIKE '%{train_depot_name}%'
        """
        conn = get_db_connection()
        s2_admin_users = execute_query(conn, s2_admin_query)
        
        railway_admin_query = f"""
            SELECT u.* 
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            WHERE ut.name IN ('railway admin', 'railway officer') 
            AND u.depo LIKE '%{train_depot_name}%'
        """

        railway_admin_users = execute_query(conn, railway_admin_query)
        
        # Updated query to get train access users with better filtering
        assigned_users_query = """
            SELECT u.email, u.id, u.first_name, u.last_name, ta.train_details
            FROM user_onboarding_user u
            JOIN trains_trainaccess ta ON ta.user_id = u.id
            WHERE ta.train_details IS NOT NULL 
            AND ta.train_details != '{}'
            AND ta.train_details != 'null'
        """
        conn = get_db_connection()
        assigned_users_raw = execute_query(conn, assigned_users_query)
        conn.close()
        
        # Get train number and complaint date for filtering
        train_no = str(complain_details.get('train_number', '')).strip()
        
        # Handle created_at whether it's a string or datetime object
        created_at_raw = complain_details.get('created_at', '')
        try:
            if isinstance(created_at_raw, datetime):
                complaint_date = created_at_raw.date()
            elif isinstance(created_at_raw, str):
                if len(created_at_raw) >= 10:
                    complaint_date = datetime.strptime(created_at_raw, "%Y-%m-%d").date()
                else:
                    complaint_date = None
            else:
                complaint_date = None
        except (ValueError, TypeError):
            complaint_date = None
            

        if complaint_date and train_no:
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
                                origin_date = datetime.strptime(access.get('origin_date', ''), "%Y-%m-%d").date()
                                end_date_str = access.get('end_date', '')
                                
                                # Check if complaint date falls within the valid range
                                if end_date_str == 'ongoing':
                                    is_valid = complaint_date >= origin_date
                                else:
                                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                                    is_valid = origin_date <= complaint_date <= end_date
                                
                                if is_valid:
                                    assigned_users_list.append(user)
                                    break  # Only need one match per user
                                    
                            except (ValueError, TypeError) as date_error:
                                logging.warning(f"Date parsing error for user {user.get('id')}: {date_error}")
                                continue
                                
                except (json.JSONDecodeError, TypeError) as json_error:
                    logging.warning(f"JSON parsing error for user {user.get('id')}: {json_error}")
                    continue

        # Combine all users and collect unique emails
        all_users_to_mail = war_room_user_in_depot + s2_admin_users + railway_admin_users + assigned_users_list
     
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
            "complaint_date": complaint_date,
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
        
        if not unique_emails:
            logging.info(f"No users found for depot {train_depo} and train {train_no} in complaint {complain_details['complain_id']}")
            return {"status": "success", "message": "No users found for this depot and train"}
        
        # Send single email with first recipient as TO and rest as CC
        primary_recipient = [unique_emails[0]]
        cc_recipients = unique_emails[1:] if len(unique_emails) > 1 else []
        
        try:
            success = send_plain_mail(subject, message, EMAIL_SENDER, primary_recipient, cc_recipients)
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
        logging.error(f"Error in send_passenger_complain_email: {e}")
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