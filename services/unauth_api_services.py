import os
import io
import logging
import uuid
import threading
import re
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from google.cloud import storage
from PIL import Image
from moviepy.editor import VideoFileClip
from urllib.parse import unquote
from database import get_db_connection, execute_query, execute_query_one
from utils.email_utils import send_plain_mail, send_passenger_complain_notifications
from dotenv import load_dotenv
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
import asyncio
import requests
from utils.train_journey_utils import is_user_assigned_on_journey_date
import sys

os.makedirs("logs", exist_ok=True)

# Get logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture all levels

# Remove existing handlers to avoid duplicates
if logger.handlers:
    logger.handlers.clear()

# Console handler - shows INFO and above
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)
console_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_format)

# File handler for all logs - saves INFO and above
file_handler = logging.FileHandler("logs/rs_logs.log")
file_handler.setLevel(logging.WARNING)  # Changed from ERROR to INFO
file_format = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
file_handler.setFormatter(file_format)

# Add handlers
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Prevent propagation to root logger (avoids duplicate logs)
logger.propagate = False

load_dotenv()

# Configuration from environment
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'sanchalak-media-bucket1')
PROJECT_ID = os.getenv('PROJECT_ID', 'sanchalak-423912')


def get_gcs_client():
    """Get authenticated GCS client using environment variables"""
    try:
        # storage.Client() will automatically use GOOGLE_APPLICATION_CREDENTIALS from .env
        client = storage.Client(project=PROJECT_ID)
        return client
    except Exception as e:
        print(f"Failed to create GCS client: {e}")
        raise

def get_valid_filename(filename):
    """
    Replace django.utils.text.get_valid_filename functionality
    """
    filename = re.sub(r'[^\w\s-]', '', filename).strip()
    filename = re.sub(r'[-\s]+', '-', filename)
    return filename

def sanitize_timestamp(raw_timestamp):
    """Sanitize timestamp for filename"""
    decoded = unquote(raw_timestamp)
    return get_valid_filename(decoded).replace(":", "_")

def process_media_file_upload(file_bytes, filename, content_type, product_name, username, folder_name):
    try:
        base_url = os.getenv("MEDIA_UPLOAD_MS_URL")
        if not base_url:
            raise ValueError("MEDIA_UPLOAD_MS_URL is not configured")

        is_video = content_type.startswith("video/")
        file_type = "video" if is_video else "image"
        endpoint = f"{base_url}/upload-video" if is_video else f"{base_url}/upload-image"
        
        files = {file_type: (filename, file_bytes, content_type)}

        data = {
            "product_name": product_name,
            "username": username,
            "folder_name": folder_name
        }

        response = requests.post(
            endpoint,
            files=files,
            data=data,
            timeout=20
        )

        response.raise_for_status()
        result = response.json()

        # Media MS may return different keys
        if "data_url" in result:
            return result["data_url"]
        if "image_url" in result:
            return result["image_url"]
        if "url" in result:
            return result["url"]

        raise ValueError(f"Unexpected media upload response: {result}")

    except Exception as e:
        logger.exception("RailSathi Media upload failed")
        raise e

def upload_file_thread(file_obj, complain_id, user):
    """Upload file in a separate thread with improved error handling"""
    try:
        logger.info(f"Starting file upload for complaint {complain_id}, file: {getattr(file_obj, 'filename', 'unknown')}")
        
        # Read file content - handle both FastAPI UploadFile and regular file objects
        if hasattr(file_obj, 'read'):
            if asyncio.iscoroutinefunction(file_obj.read):
                # For async UploadFile, we need to handle this differently
                logger.error("Async file read not supported in thread context")
                return
            file_content = file_obj.read()
        else:
            file_content = file_obj.file.read()
        
        logger.info(f"File content size: {len(file_content)} bytes")
        
        filename = getattr(file_obj, 'filename', 'unknown')
        content_type = getattr(file_obj, 'content_type', 'application/octet-stream')
        
        logger.info(f"Processing file: {filename}, content_type: {content_type}")
        
        _, ext = os.path.splitext(filename)
        ext = ext.lstrip('.').lower()
        
        # Determine media type
        if content_type.startswith("image"):
            media_type = "image"
        elif content_type.startswith("video"):
            media_type = "video"
        else:
            logger.warning(f"Unsupported media type for file: {filename}, content_type: {content_type}")
            return

        logger.info(f"Uploading {media_type} file: {filename}")
        
        # Upload file
        uploaded_url = process_media_file_upload(
            file_bytes=file_content,
            filename=filename,
            content_type=content_type,
            product_name="railsathi",
            username=user,
            folder_name="railsathi"
        )
        
        if uploaded_url:
            logger.info(f"File uploaded successfully: {uploaded_url}")
            
            # Insert media record into database
            conn = get_db_connection()
            try:
                query = """
                    INSERT INTO rail_sathi_railsathicomplainmedia 
                    (complain_id, media_type, media_url, created_by, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                now = datetime.now()
                cursor = conn.cursor()
                cursor.execute(query, (complain_id, media_type, uploaded_url, user, now, now))
                conn.commit()
                logger.info(f"Media record created successfully for complaint {complain_id}")
            except Exception as db_error:
                logger.error(f"Database error while saving media record: {db_error}")
                conn.rollback()
            finally:
                conn.close()
        else:
            logger.error(f"File upload failed for complaint {complain_id}: {filename}")
            
    except Exception as e:
        logger.error(f"Error in upload_file_thread for file {getattr(file_obj, 'filename', 'unknown')}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

async def upload_file_async(file_obj: UploadFile, complain_id: int, user: str):
    """Async version of file upload"""
    try:
        logger.info(f"Starting async file upload for complaint {complain_id}, file: {file_obj.filename}")
        
        # Read file content asynchronously
        file_content = await file_obj.read()
        logger.info(f"File content size: {len(file_content)} bytes")
        
        filename = file_obj.filename
        content_type = file_obj.content_type
        
        logger.info(f"Processing file: {filename}, content_type: {content_type}")
        
        _, ext = os.path.splitext(filename)
        ext = ext.lstrip('.').lower()
        
        # Determine media type
        if content_type.startswith("image"):
            media_type = "image"
        elif content_type.startswith("video"):
            media_type = "video"
        else:
            logger.warning(f"Unsupported media type for file: {filename}, content_type: {content_type}")
            return False

        logger.info(f"Uploading {media_type} file: {filename}")
        
        # Upload file
        uploaded_url = process_media_file_upload(
            file_bytes=file_content,
            filename=filename,
            content_type=content_type,
            product_name="railsathi",
            username=user,
            folder_name="railsathi"
        )
        
        if uploaded_url:
            logger.info(f"File uploaded successfully: {uploaded_url}")
            
            # Insert media record into database
            conn = get_db_connection()
            try:
                query = """
                    INSERT INTO rail_sathi_railsathicomplainmedia 
                    (complain_id, media_type, media_url, created_by, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                now = datetime.now()
                cursor = conn.cursor()
                cursor.execute(query, (complain_id, media_type, uploaded_url, user, now, now))
                conn.commit()
                logger.info(f"Media record created successfully for complaint {complain_id}")
                return True
            except Exception as db_error:
                logger.error(f"Database error while saving media record: {db_error}")
                conn.rollback()
                return False
            finally:
                conn.close()
        else:
            logger.error(f"File upload failed for complaint {complain_id}: {filename}")
            return False
            
    except Exception as e:
        logger.error(f"Error in upload_file_async for file {file_obj.filename}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False

# Test function to verify setup
def test_gcs_connection():
    """Test GCS connection with .env configuration"""
    try:
        #print("=== Testing GCS Connection ===")
        #print(f"Project ID: {PROJECT_ID}")
        #print(f"Bucket Name: {GCS_BUCKET_NAME}")
        #print(f"Credentials Path: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
        
        client = get_gcs_client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        bucket.reload()  # This will fail if no access
        
        #print(f"✓ Successfully connected to bucket: {GCS_BUCKET_NAME}")
        #print(f"✓ Bucket location: {bucket.location}")
        #print(f"✓ Bucket storage class: {bucket.storage_class}")
        return True
    except Exception as e:
        #print(f"✗ Failed to connect to GCS bucket: {e}")
        return False
    
# def validate_and_process_train_data(complaint_data):
#     """Validate and process train data"""
#     conn = get_db_connection()
#     try:
#         if complaint_data.get('train_id'):
#             # Get train details by ID
#             query = "SELECT * FROM trains_traindetails WHERE id = %s"
#             train = execute_query_one(conn, query, (complaint_data['train_id'],))
#             if train:
#                 complaint_data['train_number'] = train['train_no']
#                 complaint_data['train_name'] = train['train_name']
#         elif complaint_data.get('train_number'):
#             # Get train details by number
#             query = "SELECT * FROM trains_traindetails WHERE train_no = %s"
#             train = execute_query_one(conn, query, (complaint_data['train_number'],))
#             if train:
#                 complaint_data['train_id'] = train['id']
#                 complaint_data['train_name'] = train['train_name']
        
#         return complaint_data
#     finally:
#         conn.close()

def get_complaints_by_date_and_mobile_for_passengers(complain_date: date, mobile_number: str):
    """
    Fetch complaints for passengers using complain_date and mobile number
    """
    conn = get_db_connection()
    try:
        print("New function called")
        logger.info(f"Fetching passenger complaints for date={complain_date}, mobile={mobile_number}")

        query = """
            SELECT c.complain_id, c.pnr_number, c.is_pnr_validated, c.name, c.mobile_number,
                   c.complain_type, c.complain_description, c.complain_date, c.complain_status,
                   c.train_id, c.train_number, c.train_name, c.coach, c.berth_no,
                   c.submission_status, c.created_at, c.created_by, c.updated_at, c.updated_by
            FROM rail_sathi_railsathicomplain c
            WHERE c.complain_date = %s
              AND c.mobile_number::varchar = %s
            ORDER BY c.created_at DESC
        """

        params = [complain_date, mobile_number]
        return execute_query(conn, query, params)

    except Exception as e:
        logger.error(f"Error fetching passenger complaints by date and mobile: {str(e)}")
        raise
    finally:
        conn.close()

def create_complaint(complaint_data):
    """Create a new complaint"""
    conn = get_db_connection()
    try:
        # Validate and process train data
        # complaint_data = validate_and_process_train_data(complaint_data)

        # Handle date_of_journey - use current date if not provided or invalid
        date_of_journey_str = complaint_data.get('date_of_journey')
        if date_of_journey_str:
            try:
                date_of_journey = datetime.strptime(date_of_journey_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                # If date format is invalid, use current date
                date_of_journey = datetime.now()
        else:
            # If date is None or empty, use current date
            date_of_journey = datetime.now()

        # Handle complain_date
        complain_date = complaint_data.get('complain_date')
        if isinstance(complain_date, str):
            try:
                complain_date = datetime.strptime(complain_date, '%Y-%m-%d').date()
            except ValueError:
                complain_date = date.today()
        elif complain_date is None:
            complain_date = date.today()
            
        
        # Insert complaint - PostgreSQL version with RETURNING clause
        query = """
            INSERT INTO rail_sathi_railsathicomplain 
            (pnr_number, is_pnr_validated, name, mobile_number, complain_type, 
             complain_description, complain_date, date_of_journey, complain_status, train_id, 
             train_number, train_name, coach, berth_no, created_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING complain_id
        """
        now = datetime.now()
        cursor = conn.cursor()
        cursor.execute(query, (
            complaint_data.get('pnr_number'),
            complaint_data.get('is_pnr_validated', 'not-attempted'),
            complaint_data.get('name'),
            complaint_data.get('mobile_number'),
            complaint_data.get('complain_type'),
            complaint_data.get('complain_description'),
            complain_date,
            date_of_journey.date(),
            complaint_data.get('complain_status', 'pending'),
            complaint_data.get('train_id'),
            complaint_data.get('train_number'),
            complaint_data.get('train_name'),
            complaint_data.get('coach'),
            complaint_data.get('berth_no'),
            complaint_data.get('created_by'),
            now,
            now
        ))
        
        row = cursor.fetchone()
        if row:
            complain_id = row["complain_id"] if "complain_id" in row else list(row.values())[0]
        else:
            complain_id = None

        conn.commit()
        
        # Get the created complaint
        complaint = get_complaint_by_id(complain_id)
        
        # Send email in separate thread
        def _send_email(complaint_data, complaint_id):
            try:
                logger.info(f"Email thread started for complaint {complaint_id}")
                
                train_depo = ''
                if complaint_data.get('train_number'):
                    train_query = "SELECT * FROM trains_traindetails WHERE train_no = %s"
                    train_conn = get_db_connection()
                    train = execute_query_one(train_conn, train_query, (complaint_data['train_number'],))
                    train_conn.close()
                    if train:
                        train_depo = train.get('Depot', '')
                else:
                    train_depo = 'Not known'
                
                details = {
                    'train_no': complaint_data.get('train_number', ''),
                    'train_name': complaint_data.get('train_name', ''),
                    'user_phone_number': complaint_data.get('mobile_number', ''),
                    'passenger_name': complaint_data.get('name', ''),
                    'pnr': complaint_data.get('pnr_number', ''),
                    'berth': complaint_data.get('berth_no', ''),
                    'coach': complaint_data.get('coach', ''),
                    'complain_id': complaint_id,
                    'description': complaint_data.get('complain_description', ''),
                    'train_depo': train_depo,
                    'date_of_journey': date_of_journey.strftime("%d %b %Y"),
                }
                
                logger.info(f"Sending email for complaint {complaint_id} to war room users")
                send_passenger_complain_notifications(details)
                logger.info(f"Email sent successfully for complaint {complaint_id}")
            except Exception as e:
                logger.error(f"Email thread failure for complaint {complaint_id}: {str(e)}")
        
        try:
            email_thread = threading.Thread(
                target=_send_email,
                args=(complaint_data, complain_id),
                name=f"EmailThread-{complain_id}"
            )
            email_thread.daemon = True
            logger.info(f"Starting email thread for complaint {complain_id}")
            email_thread.start()
            logger.info(f"Email thread started with name {email_thread.name}")
        except Exception as e:
            logger.error(f"Failed to create email thread: {str(e)}")
        
        return complaint
    finally:
        conn.close()

def get_complaint_by_id(complain_id: int):
    """Get complaint by ID with media files"""
    conn = get_db_connection()
    try:
        # Get complaint - using string comparison by casting train_no to text
        query = """
            SELECT c.*, t.train_no, t.train_name, t."Depot" as train_depot
            FROM rail_sathi_railsathicomplain c
            LEFT JOIN trains_traindetails t ON c.train_number = t.train_no::text
            WHERE c.complain_id = %s
        """
        complaint = execute_query_one(conn, query, (complain_id,))
        print(f"Complaint fetched by id before updating: {complaint}")
        
        if not complaint:
            return None
        
        # Get media files
        media_query = """
            SELECT id, media_type, media_url, created_at, updated_at, created_by, updated_by
            FROM rail_sathi_railsathicomplainmedia
            WHERE complain_id = %s
        """
        media_files = execute_query(conn, media_query, (complain_id,))
        
        # Format response
        complaint['rail_sathi_complain_media_files'] = media_files or []
        return complaint
    finally:
        conn.close()


#def get_complaints_by_date(complain_date: date, mobile_number: str):
def get_complaints_by_date_username_depot(complain_create_date: date, username: str): #for authenticated users
    """Get complaints by date, username and depot (AUTHENTICATED USERS)"""
    conn = get_db_connection()
    try:
        user_depots_query = """
            SELECT d.depot_code
            FROM user_onboarding_user u
            INNER JOIN user_onboarding_user_depots ud ON u.id = ud.user_id
            INNER JOIN station_depot d ON ud.depot_id = d.depot_id
            WHERE u.username = %s
        """

        user_depots_result = execute_query(conn, user_depots_query, (username,))

        if not user_depots_result:
            logger.info(f"No depots found for username: {username}")
            return []
        
        depot_codes = [depot["depot_code"] for depot in user_depots_result]
        logger.info(f"User {username} has access to depots: {depot_codes}")

        train_numbers_query = """
            SELECT DISTINCT train_no
            FROM trains_traindetails
            WHERE "Depot" = ANY(%s)
        """
        train_numbers_result = execute_query(conn, train_numbers_query, (depot_codes,))

        if not train_numbers_result:
            logger.info(f"No trains found for depots: {depot_codes}")
            return []

        train_numbers = [str(train["train_no"]) for train in train_numbers_result]

        # Fixed query - using train_id instead of train.id for the foreign key
        query = """
            SELECT c.complain_id, c.pnr_number, c.is_pnr_validated, c.name, c.mobile_number,
                   c.complain_type, c.complain_description, c.complain_date, c.complain_status,
                   c.train_id, c.train_number, c.train_name, c.coach, c.berth_no,
                   c.submission_status, c.created_at, c.created_by, c.updated_at, c.updated_by,
                   t.train_name as train_detail_name, t."Depot" as train_depot
            FROM rail_sathi_railsathicomplain c
            LEFT JOIN trains_traindetails t ON c.train_id = t.id
            WHERE DATE(c.created_at) = %s AND CAST(c.train_number AS TEXT) = ANY(%s)
        """
        #complaints = execute_query(conn, query, (complain_date, mobile_number))
        complaints = execute_query(conn, query, (complain_create_date, train_numbers))
        if not complaints:
            return []
        
        # Get media files for each complaint
        for complaint in complaints:
            # Use the correct field name - complain_id should be the key
            complaint_id = complaint.get('complain_id')
            if complaint_id:
                media_query = """
                    SELECT id, media_type, media_url, created_at, updated_at, created_by, updated_by
                    FROM rail_sathi_railsathicomplainmedia
                    WHERE complain_id = %s
                """
                
                try:
                    media_conn = get_db_connection()
                    media_files = execute_query(media_conn, media_query, (complaint_id,))
                    complaint['rail_sathi_complain_media_files'] = media_files if media_files else []
                except Exception as media_error:
                    logger.error(f"Error fetching media for complaint {complaint_id}: {str(media_error)}")
                    complaint['rail_sathi_complain_media_files'] = []
                finally:
                    media_conn.close()
            else:
                complaint['rail_sathi_complain_media_files'] = []
            
            # Add missing customer_care field that's required by RailSathiComplainResponse
            complaint['customer_care'] = None 
            train_number = complaint.get('train_number')
            if train_number:
                get_depot_query = f"""
                    SELECT "Depot", train_name FROM trains_traindetails 
                    WHERE train_no = %s LIMIT 1
                """
                try:
                    train_conn = get_db_connection()
                    train_result = execute_query(train_conn, get_depot_query, (train_number,))
                    if train_result:
                        complaint['train_depot'] = train_result[0].get("Depot", "")
                        complaint['train_name'] = train_result[0].get("train_name", "")
                    else:
                        complaint['train_depot'] = ''
                        complaint['train_name'] = ''
                except Exception as e:
                    logger.error(f"[Depot Lookup] Error: {str(e)}")
                    complaint['train_depot'] = ''
                    complaint['train_name'] = ''
                finally:
                    train_conn.close()# or set appropriate default value

        return complaints
    except Exception as e:
        logger.error(f"Database error in get_complaints_by_date: {str(e)}")
        raise e
    finally:
        conn.close()
        

import json

from datetime import date, datetime, timedelta
from typing import Optional, Dict, List, Tuple, Set
import json

# Assuming these are imported from your existing modules
# from database import get_db_connection, execute_query

# Coach prefixes that require exact coach matching
EXACT_MATCH_COACH_PREFIXES = ('A', 'B', 'M', 'G', 'H', 'C')


def get_support_contacts_for_complaints(
    conn, 
    query_date: date, 
    train_coach_pairs: Set[Tuple[str, str]]
) -> Dict[Tuple[str, str], str]:
    """
    Fetch support contacts for the specific train+coach combinations.
    
    Logic:
    - If coach starts with A, B, M, G, H, C → exact coach match required
    - For other coaches (S, D, E, etc.) → find EHK user for that train+date (no coach match needed)
    
    Args:
        conn: Database connection
        query_date: The date to check assignments for
        train_coach_pairs: Set of (train_number, coach) tuples from actual complaints
        
    Returns:
        Dictionary with (train_number, coach) as key and phone number as value
    """
    cache = {}
    
    if not train_coach_pairs:
        return cache
    
    # Extract unique train numbers from complaints (normalize them)
    complaint_trains = set()
    for train_no, coach in train_coach_pairs:
        if train_no:
            complaint_trains.add(train_no)
            clean = train_no.lstrip('0') or '0'
            complaint_trains.add(clean)
    
    if not complaint_trains:
        return cache
    
    logger.info(f"Finding support contacts for {len(train_coach_pairs)} train+coach pairs, {len(complaint_trains)} unique trains")
    
    try:
        # ============================================================
        # STEP 1: Fetch journey details ONLY for trains in complaints
        # ============================================================
        train_numbers_int = []
        for t in complaint_trains:
            try:
                clean = t.lstrip('0') or '0'
                if clean.isdigit():
                    train_numbers_int.append(int(clean))
            except:
                pass
        
        train_numbers_int = list(set(train_numbers_int))
        
        if not train_numbers_int:
            logger.info("No valid train numbers to query")
            return cache
        
        train_journey_cache = {}
        train_details_query = """
            SELECT train_no, journey_duration_days, end_time
            FROM trains_traindetails
            WHERE train_no = ANY(%s)
        """
        
        train_details_result = execute_query(conn, train_details_query, (train_numbers_int,))
        
        if train_details_result:
            for row in train_details_result:
                train_no = str(row.get('train_no', ''))
                journey_duration = row.get('journey_duration_days') or 1
                end_time = row.get('end_time')
                
                if end_time and hasattr(end_time, 'strftime'):
                    end_time = end_time.strftime("%H:%M:%S")
                else:
                    end_time = "23:59:59"
                
                train_journey_cache[train_no] = {
                    "journey_duration_days": journey_duration,
                    "end_time": end_time
                }
        
        logger.info(f"Loaded journey details for {len(train_journey_cache)} trains")
        
        # ============================================================
        # STEP 2: Fetch users with train access
        # ============================================================
        assigned_users_query = """
            SELECT u.phone, u.id, ta.train_details
            FROM user_onboarding_user u
            JOIN trains_trainaccess ta ON ta.user_id = u.id
            WHERE ta.train_details IS NOT NULL 
            AND ta.train_details != '{}'
            AND ta.train_details != 'null'
            AND u.user_status = 'enabled'
            AND u.phone IS NOT NULL
            AND u.phone != ''
        """
        
        assigned_users_raw = execute_query(conn, assigned_users_query)
        
        if not assigned_users_raw:
            logger.info("No coach-assigned users found")
            return cache
        
        logger.info(f"Processing {len(assigned_users_raw)} users with train access")
        
        # ============================================================
        # STEP 3: Process assignments
        # ============================================================
        query_date_str = query_date.strftime('%Y-%m-%d')
        validation_time = datetime.combine(query_date, datetime.max.time())
        
        # Pre-compute complaint train set for fast lookup
        complaint_trains_normalized = set()
        for t in complaint_trains:
            complaint_trains_normalized.add(t)
            complaint_trains_normalized.add(t.lstrip('0') or '0')
        
        # Separate caches:
        # 1. exact_coach_cache: for coaches starting with A, B, M, G, H, C
        # 2. ehk_train_cache: for EHK users by train (no coach match needed)
        exact_coach_cache = {}  # key: (train_no, coach) -> phone
        ehk_train_cache = {}    # key: train_no -> phone (first EHK user found)
        
        users_processed = 0
        
        for user in assigned_users_raw:
            try:
                train_details_str = user.get('train_details', '{}')
                
                if isinstance(train_details_str, str):
                    train_details = json.loads(train_details_str)
                else:
                    train_details = train_details_str
                
                phone = user.get('phone', '')
                if not phone:
                    continue
                
                users_processed += 1
                
                # Only process trains that are in our complaints
                for train_no, access_list in train_details.items():
                    train_no_str = str(train_no).strip()
                    clean_train = train_no_str.lstrip('0') or '0'
                    
                    # SKIP if this train is not in our complaints
                    if train_no_str not in complaint_trains_normalized and clean_train not in complaint_trains_normalized:
                        continue
                    
                    # Get journey details from cache
                    journey_info = train_journey_cache.get(clean_train, {
                        "journey_duration_days": 1,
                        "end_time": "23:59:59"
                    })
                    
                    for access in access_list:
                        origin_date_str = access.get('origin_date', '')
                        if not origin_date_str:
                            continue
                        
                        # Get user type (ut)
                        user_type = access.get('ut', '')
                        
                        # Quick date range check
                        try:
                            origin_date = datetime.strptime(origin_date_str, "%Y-%m-%d").date()
                            journey_days = journey_info["journey_duration_days"]
                            last_date = origin_date + timedelta(days=journey_days - 1)
                            
                            # Skip if query_date is outside possible range
                            if query_date < origin_date or query_date > last_date:
                                continue
                            
                            # REMOVE THIS ENTIRE BLOCK - No time validation
                            # is_assigned = True
                            # if query_date == last_date:
                            #     try:
                            #         end_time = datetime.strptime(journey_info["end_time"], "%H:%M:%S").time()
                            #         if validation_time.time() >= end_time:
                            #             is_assigned = False
                            #     except:
                            #         pass
                            # 
                            # if not is_assigned:
                            #     continue
                            
                            # Just check coach/user type directly
                            coach_numbers = access.get("coach_numbers", [])
                            
                            # Store in exact_coach_cache for exact matching (A, B, M, G, H, C coaches)
                            for coach in coach_numbers:
                                coach_upper = str(coach).strip().upper()
                                
                                # Add to exact coach cache
                                key1 = (train_no_str, coach_upper)
                                key2 = (clean_train, coach_upper)
                                
                                if key1 not in exact_coach_cache:
                                    exact_coach_cache[key1] = phone
                                if key2 not in exact_coach_cache:
                                    exact_coach_cache[key2] = phone
                            
                            # If user is EHK, also store in ehk_train_cache for non-exact matching
                            if user_type == 'EHK':
                                current_entry = ehk_train_cache.get(train_no_str)
                                if current_entry is None or origin_date > current_entry[1]:
                                    ehk_train_cache[train_no_str] = (phone, origin_date)
                                
                                current_entry_clean = ehk_train_cache.get(clean_train)
                                if current_entry_clean is None or origin_date > current_entry_clean[1]:
                                    ehk_train_cache[clean_train] = (phone, origin_date)
                            
                        except (ValueError, TypeError):
                            continue
                            
            except (json.JSONDecodeError, TypeError):
                continue
        
        logger.info(f"Processed {users_processed} users")
        logger.info(f"Exact coach cache: {len(exact_coach_cache)} entries")
        logger.info(f"EHK train cache: {len(ehk_train_cache)} entries")
        
        # ADD THIS: Log specific keys we care about
        logger.info(f"exact_coach_cache keys for train 12333: {[k for k in exact_coach_cache.keys() if '12333' in str(k)]}")
        logger.info(f"exact_coach_cache[('12333', 'A1')] = {exact_coach_cache.get(('12333', 'A1'), 'NOT FOUND')}")
        
        
        # ============================================================
        # STEP 4: Build final cache based on coach prefix rules
        # ============================================================
        for train_no, coach in train_coach_pairs:
            if not train_no or not coach:
                continue
            
            coach_upper = coach.strip().upper()
            train_no_str = str(train_no).strip()
            clean_train = train_no_str.lstrip('0') or '0'
            
            support_contact = ''
            
            # Check if coach requires exact matching (starts with A, B, M, G, H, C)
            if coach_upper.startswith(EXACT_MATCH_COACH_PREFIXES):
                # Exact coach match required
                key1 = (train_no_str, coach_upper)
                key2 = (clean_train, coach_upper)
                
                support_contact = exact_coach_cache.get(key1) or exact_coach_cache.get(key2) or ''
                logger.info(f"Cache contains key ('12333', 'A1'): {('12333', 'A1') in exact_coach_cache}")
                logger.info(f"Cache contains key ('12333', 'A1'): {exact_coach_cache.get(('12333', 'A1'), 'NOT FOUND')}")
                logger.info(f"STEP4 exact match lookup: key1={key1}, key2={key2}, "
                       f"exact_cache.get(key1)={exact_coach_cache.get(key1, 'MISS')}, "
                       f"exact_cache.get(key2)={exact_coach_cache.get(key2, 'MISS')}, "
                       f"final support_contact={support_contact!r}")

                
                if support_contact:
                    logger.debug(f"Exact match found for train={train_no_str}, coach={coach_upper}")
            else:
                # For other coaches (S, D, E, etc.) - find EHK user for train (no coach match)
                ehk_entry = ehk_train_cache.get(train_no_str) or ehk_train_cache.get(clean_train)
                support_contact = ehk_entry[0] if ehk_entry else ''
                
                if not support_contact:
                    logger.warning(f"No EHK match for train={train_no_str}, coach={coach_upper}")
                
                if support_contact:
                    logger.debug(f"EHK match found for train={train_no_str}, coach={coach_upper}, contact={support_contact}")
                else:
                    logger.warning(f"No EHK match for train={train_no_str}, coach={coach_upper}")
            
            # Store in final cache
            cache[(train_no_str, coach_upper)] = support_contact
            cache[(clean_train, coach_upper)] = support_contact
            
            if train_no_str == '12333' and coach_upper == 'A1':
                logger.info(f"STEP4 storing cache[('12333', 'A1')] = {support_contact!r}")
            
            if not train_no_str.startswith('0'):
                cache[('0' + train_no_str, coach_upper)] = support_contact
        
        logger.info(f"Final support_contact cache: {len(cache)} entries")
        logger.info(f"Final cache[('12333', 'A1')] = {cache.get(('12333', 'A1'), 'NOT FOUND')}")
        if logger.isEnabledFor(logging.DEBUG):
            sample_keys = list(cache.keys())[:10]
            logger.debug(f"Sample cache keys: {sample_keys}")
            
        # Log some sample matches for debugging
        matched_count = sum(1 for v in cache.values() if v)
        logger.info(f"Complaints with support_contact: {matched_count}/{len(cache)}")
        
        return cache
        
    except Exception as e:
        logger.error(f"Error in get_support_contacts_for_complaints: {str(e)}")
        return cache


def get_complaints_by_date_and_mobile(complain_create_date: date, mobile_number: Optional[str] = None):
    """Get complaints by date and optionally filtered by user's depot trains"""
    conn = get_db_connection()
    try:
        # ============================================================
        # STEP 1: Fetch complaints FIRST
        # ============================================================
        if mobile_number:
            logger.info(f"Fetching complaints for mobile: {mobile_number}, date: {complain_create_date}")
            
            user_depots_query = """
                SELECT d.depot_code, d.depot_name
                FROM user_onboarding_user u
                INNER JOIN user_onboarding_user_depots ud ON u.id = ud.user_id
                INNER JOIN station_depot d ON ud.depot_id = d.depot_id
                WHERE u.phone = %s
            """
            user_depots_result = execute_query(conn, user_depots_query, (mobile_number,))
            
            if not user_depots_result:
                logger.info(f"No depots found for mobile number: {mobile_number}")
                return []
            
            depot_codes = [depot['depot_code'] for depot in user_depots_result]
            
            train_numbers_query = """
                SELECT DISTINCT train_no
                FROM trains_traindetails
                WHERE "Depot" = ANY(%s)
            """
            train_numbers_result = execute_query(conn, train_numbers_query, (depot_codes,))
            
            if not train_numbers_result:
                logger.info(f"No trains found for depots")
                return []
            
            train_numbers = []
            for train in train_numbers_result:
                train_no = str(train['train_no'])
                train_numbers.append(train_no)
                train_numbers.append('0' + train_no)
                if train_no.startswith('0'):
                    train_numbers.append(train_no.lstrip('0') or '0')
            
            unique_train_numbers = list(set(train_numbers))
            
            query = """
                SELECT c.complain_id, c.pnr_number, c.is_pnr_validated, c.name, c.mobile_number,
                       c.complain_type, c.complain_description, c.complain_date, c.complain_status,
                       c.train_id, c.train_number, c.train_name, c.coach, c.berth_no,
                       c.submission_status, c.created_at, c.created_by, c.updated_at, c.updated_by,
                       t.train_name as train_detail_name, t."Depot" as train_depot
                FROM rail_sathi_railsathicomplain c
                LEFT JOIN trains_traindetails t ON CAST(t.train_no AS VARCHAR) = c.train_number
                WHERE DATE(c.created_at) = %s
                  AND c.train_number = ANY(%s)
                ORDER BY c.created_at DESC
            """
            params = [complain_create_date, unique_train_numbers]
        else:
            logger.info(f"Fetching all complaints for date: {complain_create_date}")
            
            query = """
                SELECT c.complain_id, c.pnr_number, c.is_pnr_validated, c.name, c.mobile_number,
                       c.complain_type, c.complain_description, c.complain_date, c.complain_status,
                       c.train_id, c.train_number, c.train_name, c.coach, c.berth_no,
                       c.submission_status, c.created_at, c.created_by, c.updated_at, c.updated_by,
                       t.train_name as train_detail_name, t."Depot" as train_depot
                FROM rail_sathi_railsathicomplain c
                LEFT JOIN trains_traindetails t ON CAST(t.train_no AS VARCHAR) = c.train_number
                WHERE DATE(c.created_at) = %s
                ORDER BY c.created_at DESC
            """
            params = [complain_create_date]
        
        complaints = execute_query(conn, query, params)

        if not complaints:
            logger.info(f"No complaints found")
            return []
        
        logger.info(f"Found {len(complaints)} complaints for date {complain_create_date}")
        
        # ============================================================
        # STEP 2: Extract unique train+coach pairs from complaints
        # ============================================================
        train_coach_pairs: Set[Tuple[str, str]] = set()
        for complaint in complaints:
            train_number = str(complaint.get('train_number', '')).strip()
            coach = str(complaint.get('coach', '')).strip().upper()
            if train_number and coach:
                train_coach_pairs.add((train_number, coach))
                clean_train = train_number.lstrip('0') or '0'
                train_coach_pairs.add((clean_train, coach))
        
        logger.info(f"Unique train+coach pairs in complaints: {len(train_coach_pairs)}")
        
        # ============================================================
        # STEP 3: Get support contacts with new coach prefix logic
        # ============================================================
        support_contact_cache = get_support_contacts_for_complaints(conn, complain_create_date, train_coach_pairs)
        logger.info(f"Support contact cache: {len(support_contact_cache)} entries")

        
        for train_no, coach in train_coach_pairs:
            logger.info(f"STEP4: Looking up train_no={train_no!r}, coach={coach!r}")
        # ============================================================
        # STEP 4: Batch fetch media files
        # ============================================================
        complaint_ids = [c.get('complain_id') for c in complaints if c.get('complain_id')]
        
        media_cache = {}
        if complaint_ids:
            media_query = """
                SELECT complain_id, id, media_type, media_url, created_at, updated_at, created_by, updated_by
                FROM rail_sathi_railsathicomplainmedia
                WHERE complain_id = ANY(%s)
            """
            try:
                media_files = execute_query(conn, media_query, (complaint_ids,))
                if media_files:
                    for media in media_files:
                        cid = media.get('complain_id')
                        if cid not in media_cache:
                            media_cache[cid] = []
                        media_cache[cid].append(media)
            except Exception as media_error:
                logger.error(f"Error fetching media: {str(media_error)}")
        
        # ============================================================
        # STEP 5: Process each complaint
        # ============================================================
        for complaint in complaints:
            complaint_id = complaint.get('complain_id')
            
            complaint['rail_sathi_complain_media_files'] = media_cache.get(complaint_id, [])
            complaint['customer_care'] = None
            complaint['train_depot'] = complaint.get('train_depot', '')
            complaint['train_name'] = complaint.get('train_detail_name') or complaint.get('train_name', '')
            
            # Support contact lookup with better matching
            train_number = str(complaint.get('train_number', '')).strip()
            coach = str(complaint.get('coach', '')).strip().upper()
            
            support_contact = ''
            if train_number and coach:
                # Try original train number first
                cache_key = (train_number, coach)
                support_contact = support_contact_cache.get(cache_key, '')
                
                if train_number == '12333' and coach == 'A1':
                    logger.info(f"STEP5 lookup: cache_key={cache_key}, "
                               f"support_contact_cache.get({cache_key})={support_contact_cache.get(cache_key, 'MISS')}, "
                               f"all 12333 keys in cache: {[k for k in support_contact_cache.keys() if '12333' in str(k)]}")
                
                                            
                # Try with leading zero
                if not support_contact:
                    cache_key_with_zero = ('0' + train_number, coach)
                    support_contact = support_contact_cache.get(cache_key_with_zero, '')
                
                # Try cleaned train number (remove leading zeros)
                if not support_contact:
                    clean_train = train_number.lstrip('0') or '0'
                    cache_key_clean = (clean_train, coach)
                    support_contact = support_contact_cache.get(cache_key_clean, '')
                
                # Debug log if still not found
                if not support_contact:
                    logger.warning(f"No support contact found for train={train_number}, coach={coach}")
                    # Log what keys we tried
                    logger.debug(f"Tried keys: {cache_key}, {cache_key_with_zero if 'cache_key_with_zero' in locals() else 'N/A'}, {cache_key_clean if 'cache_key_clean' in locals() else 'N/A'}")
            
            complaint['support_contact'] = support_contact

        logger.info(f"Successfully processed {len(complaints)} complaints")
        return complaints
        
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        raise e
    finally:
        conn.close()

def update_complaint(complain_id: int, update_data: dict):
    """Update complaint and trigger passenger complaint email"""
    conn = get_db_connection()
    try:
        # Validate and process train data
        # update_data = validate_and_process_train_data(update_data)
        
        # Parse complain_date if it's a string
        if 'complain_date' in update_data and isinstance(update_data['complain_date'], str):
            try:
                update_data['complain_date'] = datetime.strptime(update_data['complain_date'], '%Y-%m-%d').date()
            except ValueError:
                pass  # Keep original value if parsing fails
        
        # Build dynamic update query
        update_fields = []
        values = []
        
        allowed_fields = [
            'pnr_number', 'is_pnr_validated', 'name', 'mobile_number', 
            'complain_type', 'complain_description', 'complain_date', 
            'complain_status', 'train_id', 'train_number', 'train_name', 
            'coach', 'berth_no', 'updated_by', 'date_of_journey', 'submission_status'
        ]
        
        for field in allowed_fields:
            if field in update_data:
                update_fields.append(f"{field} = %s")
                values.append(update_data[field])
        
        if not update_fields:
            return get_complaint_by_id(complain_id)
        
        # Add updated_at
        update_fields.append("updated_at = %s")
        values.append(datetime.now())
        values.append(complain_id)
        
        query = f"""
            UPDATE rail_sathi_railsathicomplain 
            SET {', '.join(update_fields)}
            WHERE complain_id = %s
        """
        
        cursor = conn.cursor()
        cursor.execute(query, tuple(values))
        conn.commit()
        
        # ✅ Get updated complaint data for email
        updated_complaint = get_complaint_by_id(complain_id)
        
        # ✅ Send passenger complaint email in separate thread (same as create_complaint)
        def _send_email(complaint_data, complaint_id):

            try:
                logger.info(f"Email thread started for updated complaint {complaint_id}")
                
                # Handle date_of_journey - use current date if not provided or invalid
                date_of_journey_str = complaint_data.get('date_of_journey') or complaint_data.get('complain_date')
                if date_of_journey_str:
                    try:
                        if isinstance(date_of_journey_str, str):
                            date_of_journey = datetime.strptime(date_of_journey_str, "%Y-%m-%d")
                        else:
                            date_of_journey = datetime.combine(date_of_journey_str, datetime.min.time())
                    except (ValueError, TypeError):
                        date_of_journey = datetime.now()
                else:
                    date_of_journey = datetime.now()
                
                train_depo = ''

                if complaint_data.get('train_number'):
                    print(f"Fetching train depot for train number: {complaint_data['train_number']}")

                    train_query = "SELECT * FROM trains_traindetails WHERE train_no = %s"
                    train_conn = get_db_connection()
                    train = execute_query_one(train_conn, train_query, (complaint_data['train_number'],))
                    train_conn.close()
                    if train:
                        train_depo = train.get('Depot', '')

                else:
                    train_depo = 'Not known'
                    

                
                details = {
                    'train_no': complaint_data.get('train_number', ''),
                    'train_name': complaint_data.get('train_name', ''),
                    'user_phone_number': complaint_data.get('mobile_number', ''),
                    'passenger_name': complaint_data.get('name', ''),
                    'pnr': complaint_data.get('pnr_number', ''),
                    'berth': complaint_data.get('berth_no', ''),
                    'coach': complaint_data.get('coach', ''),
                    'complain_id': complaint_id,
                    'description': complaint_data.get('complain_description', ''),
                    'train_depo': train_depo,
                    'date_of_journey': date_of_journey.strftime("%d %b %Y"),
                }
                
                logger.info(f"Sending passenger complaint email for updated complaint {complaint_id} to war room users")
                send_passenger_complain_notifications(details)
                logger.info(f"Passenger complaint email sent successfully for updated complaint {complaint_id}")
            except Exception as e:
                logger.error(f"Email thread failure for updated complaint {complaint_id}: {str(e)}")
        
        try:
            email_thread = threading.Thread(
                target=_send_email,
                args=(updated_complaint, complain_id),
                name=f"EmailThread-Update-{complain_id}"
            )
            email_thread.daemon = True
            logger.info(f"Starting passenger complaint email thread for updated complaint {complain_id}")
            email_thread.start()
            logger.info(f"Passenger complaint email thread started with name {email_thread.name}")
        except Exception as e:
            logger.error(f"Failed to create passenger complaint email thread: {str(e)}")
        
        return updated_complaint
    finally:
        conn.close()

def delete_complaint(complain_id: int):
    """Delete complaint and its media files"""
    conn = get_db_connection()
    try:
        # First delete media files
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rail_sathi_railsathicomplainmedia WHERE complain_id = %s", (complain_id,))
        
        # Then delete complaint
        cursor.execute("DELETE FROM rail_sathi_railsathicomplain WHERE complain_id = %s", (complain_id,))
        deleted_count = cursor.rowcount
        conn.commit()
        
        return deleted_count
    finally:
        conn.close()

def delete_complaint_media(complain_id: int, media_ids: List[int]):
    """Delete specific media files from complaint"""
    conn = get_db_connection()
    try:
        if not media_ids:
            return 0
        
        # PostgreSQL uses ANY() for IN clause with arrays
        query = """
            DELETE FROM rail_sathi_railsathicomplainmedia 
            WHERE complain_id = %s AND id = ANY(%s)
        """
        
        cursor = conn.cursor()
        cursor.execute(query, (complain_id, media_ids))
        deleted_count = cursor.rowcount
        conn.commit()
        
        return deleted_count
    finally:
        conn.close()

def validate_complaint_access(complain_id: int, user_name: str, mobile_number: str):
    """Validate if user can access/modify the complaint"""
    conn = get_db_connection()
    try:
        query = """
            SELECT created_by, mobile_number, complain_status 
            FROM rail_sathi_railsathicomplain 
            WHERE complain_id = %s
        """
        complaint = execute_query_one(conn, query, (complain_id,))
        
        if not complaint:
            return False, "Complaint not found"
        
        if (complaint['created_by'] != user_name or 
            complaint['mobile_number'] != mobile_number or 
            complaint['complain_status'] == "completed"):
            return False, "Only user who created the complaint can update it."
        
        return True, None
    finally:
        conn.close()