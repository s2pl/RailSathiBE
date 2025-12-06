import logging
import json
from database import get_db_connection, execute_query
from datetime import datetime
from typing import Dict, List
import pytz

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def debug_user_lists(complain_details: Dict, verbose: bool = True):
    """
    Debug function to check user lists without sending emails
    Returns detailed information about each user category
    """
    
    # Initialize lists
    war_room_user_in_depot = []
    s2_admin_users = []
    railway_admin_users = []
    assigned_users_list = []
    
    # Extract complaint details
    train_depo = complain_details.get('train_depot', '')
    train_no = str(complain_details.get('train_no', '')).strip()
    complaint_date = complain_details.get('created_at', '') 
    complain_id = complain_details.get('complain_id', 'N/A')
    
    print(f"\n{'='*80}")
    print(f"DEBUGGING USER LISTS FOR COMPLAINT ID: {complain_id}")
    print(f"{'='*80}")
    print(f"Train Depot: {train_depo}")
    print(f"Train Number: {train_no}")
    print(f"Complaint Date: {complaint_date}")
    print(f"{'='*80}\n")
    
    try:
        # 1. WAR ROOM USERS
                # 1. WAR ROOM USERS (UPDATED LOGIC)
        print("1. CHECKING WAR ROOM USERS...")
        print("-" * 50)

        # Step 1: Get Depot for the train number
        get_depot_query = f"""
            SELECT "Depot" FROM trains_traindetails 
            WHERE train_no = '{train_no}' LIMIT 1
        """
        conn = get_db_connection()
        depot_result = execute_query(conn, get_depot_query)
        conn.close()

        train_depot_name = depot_result[0]['Depot'] if depot_result else ''
        print(f"Fetched Depot from TrainDetails for Train No {train_no}: {train_depot_name}")

        # Step 2: Fetch war room users whose `depo` matches the train depot
        war_room_user_query = f"""
            SELECT u.id, u.email, u.first_name, u.last_name, u.depo
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            WHERE ut.name = 'war room user' AND u.depo LIKE '%%{train_depot_name}%%'
        """
        conn = get_db_connection()
        war_room_user_in_depot = execute_query(conn, war_room_user_query)
        conn.close()

        print(f"Total war room users matching depot '{train_depot_name}': {len(war_room_user_in_depot)}")
        if war_room_user_in_depot and verbose:
            for user in war_room_user_in_depot:
                print(f"  - ID: {user.get('id')}, Email: {user.get('email')}, "
                      f"Name: {user.get('first_name', '')} {user.get('last_name', '')}, Depot: {user.get('depo', '')}")

        
        print(f"\nWar room users matching depot '{train_depo}': {len(war_room_user_in_depot)}")
        
        # 2. S2 ADMIN USERS
        print("\n2. CHECKING S2 ADMIN USERS...")
        print("-" * 50)
        
        s2_admin_query = """
            SELECT u.id, u.email, u.first_name, u.last_name
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            WHERE ut.name = 's2 admin'
        """
        
        conn = get_db_connection()
        s2_admin_users = execute_query(conn, s2_admin_query)
        conn.close()
        
        print(f"Total S2 admin users: {len(s2_admin_users) if s2_admin_users else 0}")
        
        if s2_admin_users and verbose:
            for user in s2_admin_users:
                print(f"  - ID: {user.get('id')}, Email: {user.get('email')}, "
                      f"Name: {user.get('first_name', '')} {user.get('last_name', '')}")
        
        # 3. RAILWAY ADMIN USERS
        print("\n3. CHECKING RAILWAY ADMIN USERS...")
        print("-" * 50)
        
        railway_admin_query = """
            SELECT u.id, u.email, u.first_name, u.last_name
            FROM user_onboarding_user u 
            JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
            WHERE ut.name = 'railway admin'
        """
        
        conn = get_db_connection()
        railway_admin_users = execute_query(conn, railway_admin_query)
        conn.close()
        
        print(f"Total railway admin users: {len(railway_admin_users) if railway_admin_users else 0}")
        
        if railway_admin_users and verbose:
            for user in railway_admin_users:
                print(f"  - ID: {user.get('id')}, Email: {user.get('email')}, "
                      f"Name: {user.get('first_name', '')} {user.get('last_name', '')}")
        
        # 4. TRAIN ACCESS USERS
        print("\n4. CHECKING TRAIN ACCESS USERS...")
        print("-" * 50)
        
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
        
        print(f"Total users with train access: {len(assigned_users_raw) if assigned_users_raw else 0}")
        
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
        
        print(f"Parsed complaint date: {complaint_date}")
        print(f"Train number for filtering: {train_no}")
        
        if complaint_date and train_no and assigned_users_raw:
            print(f"\nAnalyzing train access for train {train_no}...")
            
            for user in assigned_users_raw:
                user_id = user.get('id')
                user_email = user.get('email')
                user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}"
                
                try:
                    train_details_str = user.get('train_details', '{}')
                    
                    # Handle case where train_details might be a string or already parsed
                    if isinstance(train_details_str, str):
                        train_details = json.loads(train_details_str)
                    else:
                        train_details = train_details_str
                    
                    if verbose:
                        print(f"\n  User ID: {user_id}, Email: {user_email}, Name: {user_name}")
                        print(f"  Train details keys: {list(train_details.keys())}")
                    
                    # Check if the train number exists in train_details
                    if train_no in train_details:
                        if verbose:
                            print(f"  ✓ User has access to train {train_no}")
                        
                        for access in train_details[train_no]:
                            try:
                                origin_date = datetime.strptime(access.get('origin_date', ''), "%Y-%m-%d").date()
                                end_date_str = access.get('end_date', '')
                                
                                if verbose:
                                    print(f"    Access period: {origin_date} to {end_date_str}")
                                
                                # Check if complaint date exactly matches origin_date
                                is_valid = complaint_date == origin_date
                                if verbose:
                                    print(f"    Exact date match check (complaint_date == origin_date): {is_valid}")
                                    print(f"    Complaint date: {complaint_date}, Origin date: {origin_date}")
                                
                                if is_valid:
                                    assigned_users_list.append(user)
                                    if verbose:
                                        print(f"    ✓ USER ADDED TO NOTIFICATION LIST")
                                    break  # Only need one match per user
                                    
                            except (ValueError, TypeError) as date_error:
                                if verbose:
                                    print(f"    ✗ Date parsing error: {date_error}")
                                continue
                    else:
                        if verbose:
                            print(f"  ✗ User does not have access to train {train_no}")
                                
                except (json.JSONDecodeError, TypeError) as json_error:
                    if verbose:
                        print(f"  ✗ JSON parsing error for user {user_id}: {json_error}")
                    continue
        
        print(f"\nTrain access users matching criteria: {len(assigned_users_list)}")
        
        # 5. SUMMARY
        print(f"\n{'='*80}")
        print("FINAL SUMMARY")
        print(f"{'='*80}")
        print(f"War room users (depot match): {len(war_room_user_in_depot)}")
        print(f"S2 admin users: {len(s2_admin_users) if s2_admin_users else 0}")
        print(f"Railway admin users: {len(railway_admin_users) if railway_admin_users else 0}")
        print(f"Train access users (valid): {len(assigned_users_list)}")
        
        # Combine all users and get unique emails
        all_users = war_room_user_in_depot + (s2_admin_users or []) + (railway_admin_users or []) + assigned_users_list
        
        all_emails = []
        for user in all_users:
            email = user.get('email', '')
            if email and not email.startswith("noemail") and '@' in email:
                all_emails.append(email)
        
        unique_emails = list(dict.fromkeys(all_emails))
        
        print(f"\nTotal users to notify: {len(all_users)}")
        print(f"Unique valid emails: {len(unique_emails)}")
        
        if unique_emails:
            print(f"\nEmail addresses that would receive notification:")
            for i, email in enumerate(unique_emails):
                recipient_type = "TO" if i == 0 else "CC"
                print(f"  {recipient_type}: {email}")
        
        return {
            "war_room_users": war_room_user_in_depot,
            "s2_admin_users": s2_admin_users or [],
            "railway_admin_users": railway_admin_users or [],
            "train_access_users": assigned_users_list,
            "unique_emails": unique_emails,
            "total_recipients": len(unique_emails)
        }
        
    except Exception as e:
        print(f"Error in debug_user_lists: {e}")
        logging.error(f"Error in debug_user_lists: {e}")
        return None


def test_with_sample_complaint():
    """Test the debug function with sample complaint data"""
    
    # Sample complaint data - modify these values to test different scenarios
    sample_complaint = {
        'complain_id': 'TEST123',
        'train_depot': 'DELHI',  # Change this to test different depots
        'train_no': '12345',     # Change this to test different trains
        'train_number': '12345', # Make sure this matches train_no
        'created_at': '2025-07-09',  # Change this to test different dates
        'passenger_name': 'Test Passenger',
        'user_phone_number': '9876543210',
        'train_name': 'Test Express',
        'pnr': 'TEST123456',
        'berth': '12',
        'coach': 'B1',
        'description': 'Test complaint for debugging'
    }
    
    print("Testing with sample complaint data:")
    print(f"Complaint ID: {sample_complaint['complain_id']}")
    print(f"Train Depot: {sample_complaint['train_depot']}")
    print(f"Train Number: {sample_complaint['train_no']}")
    print(f"Date: {sample_complaint['created_at']}")
    
    result = debug_user_lists(sample_complaint, verbose=True)
    
    return result


if __name__ == "__main__":
    # Run the test
    result = test_with_sample_complaint()
    
    if result:
        print(f"\n{'='*80}")
        print("DEBUG COMPLETED SUCCESSFULLY")
        print(f"{'='*80}")
        print(f"Found {result['total_recipients']} recipients for email notification")
    else:
        print("\nDEBUG FAILED - Check logs for errors")