from datetime import datetime
import logging
from database import get_db_connection, execute_query

logger = logging.getLogger(__name__)

def test_depot_user_queries(train_number: str):
    """
    Test function to verify depot-based user queries are working correctly.
    
    Args:
        train_number: Train number to test (e.g., '12371')
        
    Returns:
        dict: Detailed results of all queries
    """
    print(f"\n{'='*80}")
    print(f"TESTING DEPOT USER QUERIES FOR TRAIN: {train_number}")
    print(f"{'='*80}\n")
    
    results = {
        "train_number": train_number,
        "train_depot_code": None,
        "train_depot_name": None,
        "war_room_user_railsathi": [],
        "war_room_users": [],
        "s2_admin_users": [],
        "railway_admin_users": [],
        "train_access_users": [],
        "errors": []
    }
    
    # Step 1: Get depot information for the train
    print("Step 1: Fetching depot information...")
    print("-" * 80)
    
    depot_query = f"""
        SELECT "Depot" FROM trains_traindetails 
        WHERE train_no = '{train_number}' LIMIT 1
    """
    
    try:
        conn = get_db_connection()
        depot_result = execute_query(conn, depot_query)
        conn.close()
        
        if depot_result and len(depot_result) > 0:
            train_depot_code = depot_result[0].get('Depot', '')
            results["train_depot_code"] = train_depot_code
            print(f"✓ Train Depot Code: {train_depot_code}")
            
            # Get depot full name
            depot_name_query = f"""
                SELECT depot_name FROM station_depot 
                WHERE depot_code = '{train_depot_code}' LIMIT 1
            """
            conn = get_db_connection()
            depot_name_result = execute_query(conn, depot_name_query)
            conn.close()
            
            if depot_name_result:
                results["train_depot_name"] = depot_name_result[0].get('depot_name', '')
                print(f"✓ Train Depot Name: {results['train_depot_name']}")
        else:
            print("✗ No depot found for this train")
            results["errors"].append("No depot found for train")
            return results
            
    except Exception as e:
        error_msg = f"Error fetching depot: {str(e)}"
        print(f"✗ {error_msg}")
        results["errors"].append(error_msg)
        return results
    
    train_depot_name = train_depot_code
    
    # Step 2: Fetch War Room Users (both types)
    print(f"\nStep 2: Fetching War Room Users for depot '{train_depot_name}'...")
    print("-" * 80)
    
    war_room_user_query = f"""
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.email, u.phone, 
               u.user_status, ut.name as role_name
        FROM user_onboarding_user u 
        JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
        JOIN user_onboarding_user_depots ud ON ud.user_id = u.id
        JOIN station_depot d ON d.depot_id = ud.depot_id
        WHERE ut.name IN ('war room user', 'war room user railsathi')
        AND d.depot_code = '{train_depot_name}'
        AND u.user_status = 'enabled'
        ORDER BY ut.name, u.first_name
    """
    
    try:
        conn = get_db_connection()
        war_room_users = execute_query(conn, war_room_user_query)
        conn.close()
        
        if war_room_users:
            print(f"✓ Found {len(war_room_users)} War Room User(s):\n")
            
            for user in war_room_users:
                user_dict = {
                    "id": user.get('id'),
                    "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    "email": user.get('email'),
                    "phone": user.get('phone'),
                    "role": user.get('role_name'),
                    "status": user.get('user_status')
                }
                
                # Separate by role
                if user.get('role_name') == 'war room user railsathi':
                    results["war_room_user_railsathi"].append(user_dict)
                    print(f"  🔵 WAR ROOM USER RAILSATHI:")
                else:
                    results["war_room_users"].append(user_dict)
                    print(f"  🔵 WAR ROOM USER:")
                    
                print(f"     Name: {user_dict['name']}")
                print(f"     Phone: {user_dict['phone']}")
                print(f"     Email: {user_dict['email']}")
                print(f"     Status: {user_dict['status']}")
                print()
        else:
            print("✗ No War Room Users found for this depot")
            results["errors"].append("No War Room Users found")
            
    except Exception as e:
        error_msg = f"Error fetching war room users: {str(e)}"
        print(f"✗ {error_msg}")
        results["errors"].append(error_msg)
    
    # Step 3: Fetch S2 Admin Users
    print(f"\nStep 3: Fetching S2 Admin Users for depot '{train_depot_name}'...")
    print("-" * 80)
    
    s2_admin_query = f"""
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.email, u.phone, 
               u.user_status
        FROM user_onboarding_user u 
        JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
        JOIN user_onboarding_user_depots ud ON ud.user_id = u.id
        JOIN station_depot d ON d.depot_id = ud.depot_id
        WHERE ut.name = 's2 admin'
        AND d.depot_code = '{train_depot_name}'
        AND u.user_status = 'enabled'
        ORDER BY u.first_name
    """
    
    try:
        conn = get_db_connection()
        s2_admin_users = execute_query(conn, s2_admin_query)
        conn.close()
        
        if s2_admin_users:
            print(f"✓ Found {len(s2_admin_users)} S2 Admin User(s):\n")
            
            for user in s2_admin_users:
                user_dict = {
                    "id": user.get('id'),
                    "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    "email": user.get('email'),
                    "phone": user.get('phone'),
                    "status": user.get('user_status')
                }
                results["s2_admin_users"].append(user_dict)
                
                print(f"  🟢 Name: {user_dict['name']}")
                print(f"     Phone: {user_dict['phone']}")
                print(f"     Email: {user_dict['email']}")
                print()
        else:
            print("✗ No S2 Admin Users found for this depot")
            
    except Exception as e:
        error_msg = f"Error fetching S2 admin users: {str(e)}"
        print(f"✗ {error_msg}")
        results["errors"].append(error_msg)
    
    # Step 4: Fetch Railway Admin/Officer Users
    print(f"\nStep 4: Fetching Railway Admin/Officer Users for depot '{train_depot_name}'...")
    print("-" * 80)
    
    railway_admin_query = f"""
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.email, u.phone, 
               u.user_status, ut.name as role_name
        FROM user_onboarding_user u 
        JOIN user_onboarding_roles ut ON u.user_type_id = ut.id 
        JOIN user_onboarding_user_depots ud ON ud.user_id = u.id
        JOIN station_depot d ON d.depot_id = ud.depot_id
        WHERE ut.name IN ('railway admin', 'railway officer')
        AND d.depot_code = '{train_depot_name}'
        AND u.user_status = 'enabled'
        ORDER BY ut.name, u.first_name
    """
    
    try:
        conn = get_db_connection()
        railway_admin_users = execute_query(conn, railway_admin_query)
        conn.close()
        
        if railway_admin_users:
            print(f"✓ Found {len(railway_admin_users)} Railway Admin/Officer User(s):\n")
            
            for user in railway_admin_users:
                user_dict = {
                    "id": user.get('id'),
                    "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    "email": user.get('email'),
                    "phone": user.get('phone'),
                    "role": user.get('role_name'),
                    "status": user.get('user_status')
                }
                results["railway_admin_users"].append(user_dict)
                
                print(f"  🟡 {user_dict['role'].upper()}")
                print(f"     Name: {user_dict['name']}")
                print(f"     Phone: {user_dict['phone']}")
                print(f"     Email: {user_dict['email']}")
                print()
        else:
            print("✗ No Railway Admin/Officer Users found for this depot")
            
    except Exception as e:
        error_msg = f"Error fetching railway admin users: {str(e)}"
        print(f"✗ {error_msg}")
        results["errors"].append(error_msg)
    
    # Step 5: Fetch Train Access Users (no depot filter)
    print(f"\nStep 5: Fetching Train Access Users (all depots)...")
    print("-" * 80)
    
    assigned_users_query = """
        SELECT u.email, u.id, u.first_name, u.last_name, u.fcm_token, ta.train_details
        FROM user_onboarding_user u
        JOIN trains_trainaccess ta ON ta.user_id = u.id
        WHERE ta.train_details IS NOT NULL 
        AND ta.train_details != '{}'
        AND ta.train_details != 'null'
        AND u.user_status = 'enabled'
        LIMIT 10
    """
    
    try:
        conn = get_db_connection()
        assigned_users = execute_query(conn, assigned_users_query)
        conn.close()
        
        if assigned_users:
            print(f"✓ Found {len(assigned_users)} Train Access User(s) (showing first 10):\n")
            
            for user in assigned_users:
                user_dict = {
                    "id": user.get('id'),
                    "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    "email": user.get('email'),
                    "has_fcm_token": bool(user.get('fcm_token')),
                    "train_details_preview": str(user.get('train_details', ''))[:50] + "..."
                }
                results["train_access_users"].append(user_dict)
                
                print(f"  🟣 Name: {user_dict['name']}")
                print(f"     Email: {user_dict['email']}")
                print(f"     Has FCM Token: {user_dict['has_fcm_token']}")
                print()
        else:
            print("✗ No Train Access Users found")
            
    except Exception as e:
        error_msg = f"Error fetching train access users: {str(e)}"
        print(f"✗ {error_msg}")
        results["errors"].append(error_msg)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Train Number: {train_number}")
    print(f"Depot Code: {results['train_depot_code']}")
    print(f"Depot Name: {results['train_depot_name']}")
    print(f"\nUsers Found:")
    print(f"  - War Room User RailSathi: {len(results['war_room_user_railsathi'])}")
    print(f"  - War Room Users (other): {len(results['war_room_users'])}")
    print(f"  - S2 Admin Users: {len(results['s2_admin_users'])}")
    print(f"  - Railway Admin/Officer Users: {len(results['railway_admin_users'])}")
    print(f"  - Train Access Users: {len(results['train_access_users'])}")
    
    if results['errors']:
        print(f"\n⚠️  Errors Encountered: {len(results['errors'])}")
        for error in results['errors']:
            print(f"  - {error}")
    else:
        print("\n✅ All queries executed successfully!")
    
    print("=" * 80 + "\n")
    
    return results


# Example usage:
if __name__ == "__main__":
    # Test with a train number
    results = test_depot_user_queries("12371")
    
    # You can also access the results programmatically
    print("\nProgrammatic Access Example:")
    print(f"War Room RailSathi users: {len(results['war_room_user_railsathi'])}")
    if results['war_room_user_railsathi']:
        print(f"First WRUR phone: {results['war_room_user_railsathi'][0]['phone']}")