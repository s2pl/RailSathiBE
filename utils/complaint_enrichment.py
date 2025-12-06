from datetime import datetime
import os
import logging
from database import get_db_connection, execute_query
from utils.email_utils import send_plain_mail
from services.unauth_api_services import get_complaint_by_id

logger = logging.getLogger(__name__)

async def enrich_complaint_response_and_trigger_email(
    complain_id: int,
    pnr_number: str,
    train_number: str,
    coach: str,
    berth_no: int,
    date_of_journey: str
) -> dict:
    train_depot_name = ''
    war_room_phone = ''

    if train_number:
        get_depot_query = f"""
            SELECT "Depot" FROM trains_traindetails 
            WHERE train_no = '{train_number}' LIMIT 1
        """
        conn = get_db_connection()
        try:
            depot_result = execute_query(conn, get_depot_query)
            train_depot_name = depot_result[0]['Depot'] if depot_result else ''
        except Exception as e:
            logger.error(f"[Depot Lookup] Error: {str(e)}")
        finally:
            conn.close()

    if train_depot_name:
        war_room_user_query = f"""
            SELECT DISTINCT u.phone
            FROM user_onboarding_user u
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id
            JOIN user_onboarding_user_depots ud ON ud.user_id = u.id
            JOIN station_depot d ON d.depot_id = ud.depot_id
            WHERE ut.name = 'war room user railsathi'
            AND d.depot_code = '{train_depot_name}'
            AND u.phone IS NOT NULL
            AND u.phone != ''
            AND u.is_active = TRUE
            AND u.user_status = 'enabled'
            LIMIT 1
        """
        conn = get_db_connection()
        try:
            wrur_result = execute_query(conn, war_room_user_query)
            war_room_phone = wrur_result[0]['phone'] if wrur_result else ''
        except Exception as e:
            logger.error(f"[WRUR Lookup] Error: {str(e)}")
        finally:
            conn.close()

    if not war_room_phone:
        war_room_phone = "9123183988"
        env = (os.getenv("ENV") or "LOCAL").upper()

        # Build subject based on env
        base_subject = f"{train_number} ({train_depot_name}) NO war Room User RailSathi (WRUR) Found !"

        if env in ("UAT", "LOCAL"):
            subject =f"{env} | {base_subject}"
        elif env == "PROD":
            subject = base_subject #Remove PROD prefix
        else:
            subject = f"{env} | {base_subject}"
            
        message = f"""
        No War Room User RailSathi (WRUR) exists for PNR Number: {pnr_number} in Train Number: {train_number}
        Coach/Berth: {coach}/{berth_no} on {date_of_journey}
        Train Depot: {train_depot_name}

        Kindly verify the WRUR assignment to the given train depot.
        """
        try:
            send_plain_mail(
                subject=subject,
                message=message,
                from_=os.getenv("MAIL_FROM"),
                to=["harshnmishra01@gmail.com"]
            )
        except Exception as e:
            logger.error(f"[Email Error] Could not send fallback WRUR email: {str(e)}")

    complaint_data = get_complaint_by_id(complain_id)
    complaint_data["customer_care"] = war_room_phone
    complaint_data["train_depot"] = train_depot_name

    return complaint_data
