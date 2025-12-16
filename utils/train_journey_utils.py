# utils/train_journey_utils.py

from datetime import datetime, timedelta
import logging
from database import get_db_connection, execute_query

logger = logging.getLogger(__name__)


def get_train_journey_details(train_no: str) -> dict:
    """
    Fetch journey duration and end time for a train from TrainDetails model.
    
    Args:
        train_no: Train number as string
        
    Returns:
        dict with keys: journey_duration_days (int), end_time (str in HH:MM:SS format)
    """
    try:
        conn = get_db_connection()
        result = execute_query(
            conn,
            """
            SELECT journey_duration_days, end_time 
            FROM trains_traindetails 
            WHERE train_no = %s 
            LIMIT 1
            """,
            (train_no,)
        )
        conn.close()
        
        if result and len(result) > 0:
            journey_duration = result[0].get("journey_duration_days")
            end_time = result[0].get("end_time")
            
            # Convert end_time to string format if it's a time object
            if end_time and hasattr(end_time, 'strftime'):
                end_time = end_time.strftime("%H:%M:%S")
            
            return {
                "journey_duration_days": journey_duration if journey_duration else 1,
                "end_time": end_time if end_time else "23:59:59"
            }
        else:
            logger.warning(f"No train details found for train {train_no}, using defaults")
            return {
                "journey_duration_days": 1,
                "end_time": "23:59:59"
            }
    except Exception as e:
        logger.error(f"Error fetching train journey details for {train_no}: {e}")
        return {
            "journey_duration_days": 1,
            "end_time": "23:59:59"
        }


def is_user_assigned_on_journey_date(
    origin_date_str: str,
    pnr_journey_date_str: str,
    pnr_validation_time: datetime,
    train_no: str
) -> bool:
    """
    Check if a user assigned on origin_date should be considered assigned 
    for a PNR with journey_date, considering multi-day train journeys.
    
    Logic:
    - User is assigned if pnr_journey_date falls within the range:
      [origin_date, origin_date + journey_duration_days - 1]
    - If pnr_journey_date == (origin_date + journey_duration_days - 1),
      check if pnr_validation_time < train_end_time
    
    Args:
        origin_date_str: User's assigned date in "YYYY-MM-DD" format
        pnr_journey_date_str: PNR's journey date in "YYYY-MM-DD" format
        pnr_validation_time: Datetime when PNR was validated
        train_no: Train number as string
        
    Returns:
        bool: True if user should be considered assigned, False otherwise
    """
    try:
        # Parse dates
        origin_date = datetime.strptime(origin_date_str, "%Y-%m-%d").date()
        pnr_journey_date = datetime.strptime(pnr_journey_date_str, "%Y-%m-%d").date()
        
        # Get train journey details
        train_details = get_train_journey_details(train_no)
        journey_duration_days = train_details["journey_duration_days"]
        end_time_str = train_details["end_time"]
        
        # Calculate the last day of the journey
        # journey_duration_days - 1 because if train starts day 1 and ends day 1, duration = 1
        last_journey_date = origin_date + timedelta(days=journey_duration_days - 1)
        
        logger.debug(
            f"Checking assignment: origin={origin_date}, pnr_journey={pnr_journey_date}, "
            f"last_journey_date={last_journey_date}, duration={journey_duration_days} days"
        )
        
        # Check if PNR journey date falls within the journey range
        if pnr_journey_date < origin_date:
            logger.debug(f"PNR journey date {pnr_journey_date} is before origin date {origin_date}")
            return False
        
        if pnr_journey_date > last_journey_date:
            logger.debug(
                f"PNR journey date {pnr_journey_date} is after last journey date {last_journey_date}"
            )
            return False
        
        # If PNR journey date is before the last day, user is definitely assigned
        if pnr_journey_date < last_journey_date:
            logger.debug(f"PNR journey date is within journey range (before last day)")
            return True
        
        # If PNR journey date equals the last day, check the time
        if pnr_journey_date == last_journey_date:
            try:
                # Parse end time
                end_time = datetime.strptime(end_time_str, "%H:%M:%S").time()
                
                # Get validation time (time component only)
                validation_time = pnr_validation_time.time()
                
                if validation_time < end_time:
                    logger.debug(
                        f"PNR validated at {validation_time} before train end time {end_time} on last day"
                    )
                    return True
                else:
                    logger.debug(
                        f"PNR validated at {validation_time} after train end time {end_time} on last day"
                    )
                    return False
            except Exception as time_error:
                logger.error(f"Error parsing time: {time_error}, defaulting to True for last day")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error in is_user_assigned_on_journey_date: {e}")
        # On error, fall back to exact date match
        return origin_date_str == pnr_journey_date_str