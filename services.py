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
from utils.email_utils import send_plain_mail, send_passenger_complain_email
from dotenv import load_dotenv
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def process_media_file_upload(file_content, file_format, complain_id, media_type):
    """Process and upload media file to Google Cloud Storage"""
    try:
        created_at = datetime.now().strftime("%Y-%m-%d_%H:%M:%S.%f")
        unique_id = str(uuid.uuid4())[:5]
        full_file_name = f"rail_sathi_complain_{complain_id}_{sanitize_timestamp(created_at)}_{unique_id}.{file_format}"

        # Use the authenticated client
        client = get_gcs_client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = None

        if media_type == "image":
            file_stream = io.BytesIO(file_content)
            original_image = Image.open(file_stream)
            if original_image.mode == 'RGBA':
                original_image = original_image.convert('RGB')
            new_file = io.BytesIO()
            original_image.save(new_file, format='JPEG')
            new_file.seek(0)
            key = f"rail_sathi_complain_images/{full_file_name}"
            blob = bucket.blob(key)
            blob.upload_from_file(new_file, content_type='image/jpeg')
            #print(f"rail_sathi_complain_images Image uploaded: {full_file_name}")

        elif media_type == "video":
            try:
                temp_dir = "/tmp/rail_sathi_temp"
                os.makedirs(temp_dir, exist_ok=True)
                
                temp_file_path = os.path.join(temp_dir, full_file_name)
                compressed_file_path = os.path.join(temp_dir, f"compressed_{full_file_name}")
                
                with open(temp_file_path, 'wb') as temp_file:
                    temp_file.write(file_content)
                
                clip = VideoFileClip(temp_file_path)
                target_bitrate = '5000k'
                try:
                    clip.write_videofile(compressed_file_path, codec='libx264', bitrate=target_bitrate)
                    clip.close()
                except Exception as e:
                    print(f"Error compressing video: {e}")
                
                key = f"rail_sathi_complain_videos/{full_file_name}"
                blob = bucket.blob(key)
                with open(compressed_file_path, 'rb') as temp_file:
                    blob.upload_from_file(temp_file, content_type='video/mp4')
                #print(f"rail_sathi_complain_videos Video uploaded: {full_file_name}")
            except Exception as e:
                print(f'Error while storing video: {repr(e)}')
            finally:
                if os.path.exists(compressed_file_path):
                    os.remove(compressed_file_path)
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        if blob:
            try:
                url = blob.public_url
                #print(f"Uploaded file URL: {url}")
                return url
            except Exception as e:
                print(f"Failed to get public URL: {e}")
                return None
        else:
            print("Upload failed (blob is None)")
            return None
    except Exception as e:
        print(f"Error processing media file: {e}")
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
        uploaded_url = process_media_file_upload(file_content, ext, complain_id, media_type)
        
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
        uploaded_url = process_media_file_upload(file_content, ext, complain_id, media_type)
        
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
             complain_description, complain_date, complain_status, train_id, 
             train_number, train_name, coach, berth_no, created_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        
        complain_id = cursor.fetchone()[0]
        conn.commit()
        
        # Get the created complaint
        complaint = get_complaint_by_id(complain_id)
        
        # Send email in separate thread
        def _send_email(complaint_data, complaint_id):
            try:
                logger.info(f"Email thread started for complaint {complaint_id}")
                
                train_depo = ''
                if complaint_data.get('train_id'):
                    train_query = "SELECT * FROM trains_traindetails WHERE id = %s"
                    train_conn = get_db_connection()
                    train = execute_query_one(train_conn, train_query, (complaint_data['train_id'],))
                    train_conn.close()
                    if train:
                        train_depo = train.get('Depot', '')
                elif complaint_data.get('train_number'):
                    train_query = "SELECT * FROM trains_traindetails WHERE train_no = %s"
                    train_conn = get_db_connection()
                    train = execute_query_one(train_conn, train_query, (complaint_data['train_number'],))
                    train_conn.close()
                    if train:
                        train_depo = train.get('Depot', '')
                
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
                send_passenger_complain_email(details)
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
        # Get complaint
        query = """
            SELECT c.*, t.train_no, t.train_name, t."Depot" as train_depot
            FROM rail_sathi_railsathicomplain c
            LEFT JOIN trains_traindetails t ON c.train_id = t.id
            WHERE c.complain_id = %s
        """
        complaint = execute_query_one(conn, query, (complain_id,))
        
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


def get_complaints_by_date(complain_date: date, mobile_number: str):
    """Get complaints by date and mobile number"""
    conn = get_db_connection()
    try:
        # Fixed query - using train_id instead of train.id for the foreign key
        query = """
            SELECT c.complain_id, c.pnr_number, c.is_pnr_validated, c.name, c.mobile_number,
                   c.complain_type, c.complain_description, c.complain_date, c.complain_status,
                   c.train_id, c.train_number, c.train_name, c.coach, c.berth_no,
                   c.submission_status, c.created_at, c.created_by, c.updated_at, c.updated_by,
                   t.train_name as train_detail_name, t."Depot" as train_depot
            FROM rail_sathi_railsathicomplain c
            LEFT JOIN trains_traindetails t ON c.train_id = t.id
            WHERE c.complain_date = %s AND c.mobile_number = %s
        """
        complaints = execute_query(conn, query, (complain_date, mobile_number))
        
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
                    media_files = execute_query(conn, media_query, (complaint_id,))
                    complaint['rail_sathi_complain_media_files'] = media_files if media_files else []
                except Exception as media_error:
                    logger.error(f"Error fetching media for complaint {complaint_id}: {str(media_error)}")
                    complaint['rail_sathi_complain_media_files'] = []
            else:
                complaint['rail_sathi_complain_media_files'] = []
            
            # Add missing customer_care field that's required by RailSathiComplainResponse
            complaint['customer_care'] = None 
            train_number = complaint.get('train_number')
            if train_number:
                get_depot_query = f"""
                    SELECT "Depot" FROM trains_traindetails 
                    WHERE train_no = '{train_number}' LIMIT 1
                """
                
                get_train_name_query = f"""
                    SELECT train_name FROM trains_traindetails 
                    WHERE train_no = '{train_number}' LIMIT 1
                """
                conn = get_db_connection()
                try:
                    depot_result = execute_query(conn, get_depot_query)
                    train_depot_name = depot_result[0]['Depot'] if depot_result else ''
                    train_name_result = execute_query(conn, get_train_name_query)
                    train_name = train_name_result[0]['train_name'] if train_name_result else ''
                except Exception as e:
                    logger.error(f"[Depot Lookup] Error: {str(e)}")
                finally:
                    conn.close()# or set appropriate default value
            complaint['train_depot'] = train_depot_name
            complaint['train_name'] = train_name
        
        return complaints
    except Exception as e:
        logger.error(f"Database error in get_complaints_by_date: {str(e)}")
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
                if complaint_data.get('train_id'):
                    train_query = "SELECT * FROM trains_traindetails WHERE id = %s"
                    train_conn = get_db_connection()
                    train = execute_query_one(train_conn, train_query, (complaint_data['train_id'],))
                    train_conn.close()
                    if train:
                        train_depo = train.get('Depot', '')
                elif complaint_data.get('train_number'):
                    train_query = "SELECT * FROM trains_traindetails WHERE train_no = %s"
                    train_conn = get_db_connection()
                    train = execute_query_one(train_conn, train_query, (complaint_data['train_number'],))
                    train_conn.close()
                    if train:
                        train_depo = train.get('Depot', '')
                
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
                send_passenger_complain_email(details)
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