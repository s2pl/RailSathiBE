from fastapi import APIRouter, FastAPI, HTTPException, UploadFile, File, Form, Depends ,Request,Security, APIRouter
from fastapi.responses import JSONResponse
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, date, time , timedelta
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from database import get_db_connection, execute_query_one, execute_query
from passlib.hash import django_pbkdf2_sha256
import asyncio
import threading
import logging
from services import (
    create_complaint, get_complaint_by_id, get_complaints_by_date,
    update_complaint, delete_complaint, delete_complaint_media,
    upload_file_thread
)

from utils.complaint_enrichment import enrich_complaint_response_and_trigger_email
import inspect
import json
   
from database import get_db_connection, execute_query
import os
from dotenv import load_dotenv
from utils.email_utils import send_plain_mail
from auth_models import RailSathiComplainResponse

#use router
router = APIRouter(prefix="/rs_microservice/v2", tags=["Auth Complaint APIs"])

#----------------------AUTHENTICATED APIs ----------------------#


load_dotenv()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/rs_microservice/v2/token")

#JWT configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY","fallback_dummy_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES",30))


#JWT token generator
def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=30)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta 
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

#User authentication Dependecy
def get_current_user(token: str = Depends(oauth2_scheme)):
    """Check JWT token in Authorization header"""

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid token"
                )
        return{"username": username}
    except JWTError:
        raise HTTPException(
                status_code=401,
                detail="Invalid or expired token"
            )


#Login Endpoint to get JWT token
@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint to get JWT token"""
    conn = get_db_connection()
    try:
        user = execute_query(
            conn,
            "SELECT * FROM user_onboarding_user WHERE username = %s",
            (form_data.username,)
        )
        if not user:
            raise HTTPException(status_code=401, detail="User not found or invalid credentials")
        
        if not django_pbkdf2_sha256.verify(form_data.password, user[0]['password']):
            raise HTTPException(status_code=401, detail="Incorrect password")
        
        token = create_access_token(data={"sub": user[0]['username']})
        return {"access_token": token, "token_type": "bearer"}
    
    finally:
        conn.close()

import re, time, logging
from psycopg2.extras import RealDictCursor
from passlib.context import CryptContext

# Initialize password context for hashing
pwd_context = CryptContext(schemes=["django_pbkdf2_sha256"], deprecated="auto")


@router.post("/signup")
async def signup(
    f_name: str = Form(...),
    m_name: str = Form(""),
    l_name: str = Form(...),
    phone: str = Form(...),
    whatsapp_number: str = Form(...),
    password: str = Form(...),
    re_password: str = Form(...),
    email: str = Form("noemail@gmail.com"),
    division: str = Form(None),
    zone: str = Form(None),
    depo: str = Form(None),
    emp_number: str = Form(None),
):
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # -----------------------------
        # Required fields validation
        # -----------------------------
        required_fields = ["f_name", "l_name", "phone", "password", "re_password", "whatsapp_number"]
        for field in required_fields:
            if not locals()[field]:
                raise HTTPException(status_code=400, detail=f"{field} is required")

        # -----------------------------
        # Phone & WhatsApp validation
        # -----------------------------
        if not re.match(r'^\d{10}$', phone) or phone.startswith("0"):
            raise HTTPException(status_code=400, detail="Invalid phone number")

        if not re.match(r'^\d{10}$', whatsapp_number) or whatsapp_number.startswith("0"):
            raise HTTPException(status_code=400, detail="Invalid WhatsApp number")

        # -----------------------------
        # Password match & hash
        # -----------------------------
        if password != re_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")

        # -----------------------------
        # Generate fallback email
        # -----------------------------
        if not email or email == "noemail@gmail.com":
            ts = int(time.time())
            email = f"noemailid.sanchalak.{ts}@gmail.com"

        # -----------------------------
        # Duplicate checks
        # -----------------------------
        cur.execute("""
            SELECT id FROM user_onboarding_user
            WHERE phone=%s OR whatsapp_number=%s OR email=%s
        """, (phone, whatsapp_number, email))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="User already exists")

        cur.execute("""
            SELECT id FROM user_onboarding_requestuser
            WHERE user_phone=%s OR user_whatsapp=%s OR user_email=%s
        """, (phone, whatsapp_number, email))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Signup request already pending")

        # -----------------------------
        # Insert passenger (only case now)
        # -----------------------------
        hashed_password = pwd_context.hash(password[:72])  # truncate to 72 bytes

        cur.execute("""
            INSERT INTO user_onboarding_user
            (first_name, middle_name, last_name, username, email, phone, whatsapp_number, password,
             created_at, created_by, updated_at, updated_by, is_active, staff, railway_admin, enabled,
             user_type_id, user_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,NOW(),%s,TRUE,FALSE,FALSE,TRUE,1,'active')
            RETURNING id, first_name, last_name, email, phone, whatsapp_number, username
        """, (f_name, m_name, l_name, phone, email, phone, whatsapp_number, hashed_password, phone, phone))

        new_user = cur.fetchone()
        conn.commit()
        return JSONResponse({"message": "Passenger registered successfully", "user": new_user})

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error during signup")
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")
    finally:
        conn.close()



from passlib.hash import django_pbkdf2_sha256

@router.post("/signin")
async def signin(
    phone: str = Form(...),
    password: str = Form(...)
):
    """
    Signin endpoint using mobile number and password.
    Returns JWT token if credentials are correct.
    """
    conn = get_db_connection()
    try:
        # Fetch user by phone number
        user = execute_query(
            conn,
            "SELECT * FROM user_onboarding_user WHERE phone = %s",
            (phone,)
        )

        if not user:
            raise HTTPException(status_code=401, detail="User not found or invalid credentials")

        # Verify password
        if not django_pbkdf2_sha256.verify(password, user[0]['password']):
            raise HTTPException(status_code=401, detail="Incorrect password")

        # Generate JWT token
        token = create_access_token(data={"sub": user[0]['username']})
        return JSONResponse({"access_token": token, "token_type": "bearer"})

    finally:
        conn.close()



logger = logging.getLogger("main")
@router.get("/complaint/get/{complain_id}", response_model=RailSathiComplainResponse)
async def get_complaint(
    complain_id: int,
    current_user: dict = Depends(get_current_user)):
    """Get complaint by ID"""
    try:
        complaint = get_complaint_by_id(complain_id)
        logger.info(f"Complaint fetched: {complaint}")

        if not complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")
        
        if "customer_care" not in complaint:
            complaint["customer_care"] = None
        # Wrap the complaint in the expected response format
        return RailSathiComplainResponse(
            message="Complaint retrieved successfully",
            data=complaint
        )
    
    except HTTPException:
        raise

    except Exception as e:
        logger.exception(f"Error getting complaint {complain_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/complaint/get/date/{date_str}", response_model=List[RailSathiComplainResponse])
async def get_complaints_by_date_endpoint(
    date_str: str,
    mobile_number: Optional[str] = None,
    current_user: dict = Depends(get_current_user)):
    """Get complaints by date and mobile number"""
    try:
        # Validate date format
        try:
            complaint_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
        
        if not mobile_number:
            raise HTTPException(status_code=400, detail="mobile_number parameter is required")
        
        complaints = get_complaints_by_date(complaint_date, mobile_number)
        
        # Wrap each complaint in the expected response format
        response_list = []
        for complaint in complaints:
            response_list.append(RailSathiComplainResponse(
                message="Complaint retrieved successfully",
                data=complaint
            ))
        
        return response_list
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting complaints by date {date_str}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/complaint/add", response_model=RailSathiComplainResponse)
@router.post("/complaint/add/", response_model=RailSathiComplainResponse)
async def create_complaint_endpoint_threaded(
    current_user: dict = Depends(get_current_user),

    pnr_number: Optional[str] = Form(None),
    is_pnr_validated: Optional[str] = Form("not-attempted"),
    name: Optional[str] = Form(None),
    mobile_number: Optional[str] = Form(None),
    complain_type: Optional[str] = Form(None),
    date_of_journey: Optional[str] = Form(None),
    complain_description: Optional[str] = Form(None),
    complain_date: Optional[str] = Form(None),
    complain_status: str = Form("pending"),
    train_id: Optional[int] = Form(None),
    train_number: Optional[str] = Form(None),
    train_name: Optional[str] = Form(None),
    coach: Optional[str] = Form(None),
    berth_no: Optional[int] = Form(None),
    rail_sathi_complain_media_files: List[UploadFile] = File(default=[])
):
    """Create new complaint with improved file handling"""
    try:
        print(f"Creating complaint for user: {name}")
        print(f"Number of files received: {len(rail_sathi_complain_media_files)}")
        print(f"Request data: {{"
                    f"pnr_number: {pnr_number}, "
                    f"is_pnr_validated: {is_pnr_validated}, "
                    f"name: {name}, "
                    f"mobile_number: {mobile_number}, "
                    f"complain_type: {complain_type}, "
                    f"date_of_journey: {date_of_journey}, "
                    f"complain_description: {complain_description}, "
                    f"complain_date: {complain_date}, "
                    f"complain_status: {complain_status}, "
                    f"train_id: {train_id}, "
                    f"train_number: {train_number}, "
                    f"train_name: {train_name}, "
                    f"coach: {coach}, "
                    f"berth_no: {berth_no}"
                    f"}}")

        if not current_user or "username" not in current_user:
            raise HTTPException(status_code=401, detail="User not authenticated")
        # Prepare complaint data
        complaint_data = {
            "pnr_number": pnr_number,
            "is_pnr_validated": is_pnr_validated,
            "name": name,
            "mobile_number": mobile_number,
            "complain_type": complain_type,
            "complain_description": complain_description,
            "complain_date": complain_date,
            "date_of_journey": date_of_journey,
            "complain_status": complain_status,
            "train_id": train_id,
            "train_number": train_number,
            "train_name": train_name,
            "coach": coach,
            "berth_no": berth_no,
            "created_by": current_user["username"] #changed to logged in user
        }
        
       # Initialize default values
        train_depot_name = ''
        war_room_phone = ''  # changed from list to string

        # Step 1: Get depot information
        if train_number:
            get_depot_query = f"""
                SELECT "Depot" FROM trains_traindetails 
                WHERE train_no = '{train_number}' LIMIT 1
            """
            conn = get_db_connection()
            try:
                depot_result = execute_query(conn, get_depot_query)
                train_depot_name = depot_result[0]['Depot'] if depot_result and len(depot_result) > 0 else ''
                print(f"Train depot found: {train_depot_name}")
            except Exception as e:
                logger.error(f"Error fetching depot: {str(e)}")
                train_depot_name = ''
            finally:
                conn.close()

            # Step 2: Fetch war room user phone number
            if train_depot_name:
                war_room_user_query = f"""
                    SELECT u.phone
                    FROM user_onboarding_user u
                    JOIN user_onboarding_roles ut ON u.user_type_id = ut.id
                    WHERE ut.name = 'war room user railsathi'
                    AND (
                        u.depo = '{train_depot_name}'
                        OR u.depo LIKE '{train_depot_name},%'
                        OR u.depo LIKE '%,{train_depot_name},%'
                        OR u.depo LIKE '%,{train_depot_name}'
                    )
                    AND u.phone IS NOT NULL
                    AND u.phone != ''
                    LIMIT 1
                """
                conn = get_db_connection()
                try:
                    war_room_user_in_depot = execute_query(conn, war_room_user_query)
                    war_room_phone = war_room_user_in_depot[0]['phone'] if war_room_user_in_depot else ''
                    # print(f"War room phone found: {war_room_phone}")
                except Exception as e:
                    logger.error(f"Error fetching war room user: {str(e)}")
                    war_room_phone = ''
                finally:
                    conn.close()
                    
            if not war_room_phone:
                war_room_phone = "9123183988"
                # print("Starting mail content formation for no wrur Using default war room phone: 9123183988")
                
                # Prepare email details
                env = os.getenv('ENV')
                if not train_depot_name:
                    train_depot_name = "(Not found in database)"

                if env == 'UAT':
                    subject = f"UAT | {train_number} ({train_depot_name}) No War Room User RailSathi(WRUR) Found !"
                elif env == 'PROD':
                    subject = f"{train_number} ({train_depot_name} No War Room User RailSathi(WRUR) Found !"  
                else:
                    subject = f"LOCAL | {train_number} ({train_depot_name} No War Room User RailSathi(WRUR) Found !"
                    
                message = f"""
                No War Room User RailSathi (WRUR) exists for PNR Number: {pnr_number} in Train Number: {train_number} travelling on {date_of_journey}
                in {coach}/{berth_no} 
                Train Depot: {train_depot_name} 
                
                Kindly verify the WRUR assignment to the given train depot.
                """
                
                # Send email using the plain mail function
                
                load_dotenv()  # Load environment variables from .env file
                from_ = os.getenv("MAIL_FROM")  # Get sender email from .env
                to = ["contact@suvidhaen.com"]
                # print(f"Sending war room alert email to {to} with subject '{subject}'")
                success = send_plain_mail(
                    subject=subject,
                    message=message,
                    from_=from_,
                    to=to
                )
               
                
                if success:
                    logging.info(f"War room alert email sent successfully for PNR: {pnr_number}")
                    print (f"Email sent successfully: {success}")
                else:
                    logging.error(f"Failed to send war room alert email for PNR: {pnr_number}")
                    print(f"Email sending failed: {success}")
                
        # Create complaint
        complaint = create_complaint(complaint_data)
        complain_id = complaint["complain_id"]
        # print(f"Complaint created with ID: {complain_id}")
        
        # Handle file uploads if any files are provided
        if rail_sathi_complain_media_files and len(rail_sathi_complain_media_files) > 0:
            # print(f"Processing {len(rail_sathi_complain_media_files)} files")
            
            # Read all file contents first (before threading)
            file_data_list = []
            for file_obj in rail_sathi_complain_media_files:
                if file_obj.filename:  # Check if file is actually uploaded
                    file_content = await file_obj.read()
                    file_data_list.append({
                        'content': file_content,
                        'filename': file_obj.filename,
                        'content_type': file_obj.content_type
                    })
                    print(f"Read file: {file_obj.filename}, size: {len(file_content)}")
            
            # Process files in threads
            threads = []
            for file_data in file_data_list:
                # Create a mock file object for threading
                class MockFile:
                    def __init__(self, content, filename, content_type):
                        self.content = content
                        self.filename = filename
                        self.content_type = content_type
                    
                    def read(self):
                        return self.content
                
                mock_file = MockFile(file_data['content'], file_data['filename'], file_data['content_type'])
                t = threading.Thread(
                    target=upload_file_thread, 
                    args=(mock_file, complain_id, name or ''),
                    name=f"FileUpload-{complain_id}-{file_data['filename']}"
                )
                t.start()
                threads.append(t)
                print(f"Started thread for file: {file_data['filename']}")
            
            # Wait for all threads to complete
            for t in threads:
                t.join()
                print(f"Thread completed: {t.name}")
        
        # Add a small delay to ensure database operations complete
        await asyncio.sleep(1)
        
        # Get updated complaint with media files
        updated_complaint = get_complaint_by_id(complain_id)
        updated_complaint["customer_care"] = war_room_phone
        updated_complaint["train_depot"] = train_depot_name
  

        return {
            "message": "Complaint created successfully",
            "data": updated_complaint
        }

    except Exception as e:
        logger.error(f"Error creating complaint: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.patch("/complaint/update/{complain_id}", response_model=RailSathiComplainResponse)
async def update_complaint_endpoint(
    complain_id: int,
    current_user: dict = Depends(get_current_user),

    pnr_number: Optional[str] = Form(None),
    is_pnr_validated: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    mobile_number: Optional[str] = Form(None),
    complain_type: Optional[str] = Form(None),
    complain_description: Optional[str] = Form(None),
    complain_date: Optional[str] = Form(None),
    complain_status: Optional[str] = Form(None),
    train_id: Optional[int] = Form(None),
    train_number: Optional[str] = Form(None),
    train_name: Optional[str] = Form(None),
    coach: Optional[str] = Form(None),
    berth_no: Optional[int] = Form(None),
    rail_sathi_complain_media_files: List[UploadFile] = File(default=[])
):
    """Update complaint (partial update)"""
    try:
        print(f"Updating complaint {complain_id} for user: {name}")
        print(f"Number of files received: {len(rail_sathi_complain_media_files)}")
        
        # Check if complaint exists and validate permissions
        existing_complaint = get_complaint_by_id(complain_id)

        if not existing_complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")
        
        # # Check permissions
        # if (existing_complaint["created_by"] != name or 
        #     existing_complaint["complain_status"] == "completed" or 
        #     existing_complaint["mobile_number"] != mobile_number):
        #     raise HTTPException(status_code=403, detail="Only user who created the complaint can update it.")
        
        # Prepare update data (only include non-None values)
        
        update_data = {}
        if pnr_number is not None: update_data["pnr_number"] = pnr_number
        if is_pnr_validated is not None: update_data["is_pnr_validated"] = is_pnr_validated
        if name is not None: update_data["name"] = name
        if mobile_number is not None: update_data["mobile_number"] = mobile_number
        if complain_type is not None: update_data["complain_type"] = complain_type
        if complain_description is not None: update_data["complain_description"] = complain_description
        if complain_date is not None: update_data["complain_date"] = complain_date
        if complain_status is not None: update_data["complain_status"] = complain_status
        if train_id is not None: update_data["train_id"] = train_id
        if train_number is not None: update_data["train_number"] = train_number
        if train_name is not None: update_data["train_name"] = train_name
        if coach is not None: update_data["coach"] = coach
        if berth_no is not None: update_data["berth_no"] = berth_no
        update_data["updated_by"] = name
        
        # Update complaint
        updated_complaint = update_complaint(complain_id, update_data)
        print(f"Complaint {complain_id} updated successfully")
        
        # Handle file uploads if any files are provided (similar to create endpoint)
        if rail_sathi_complain_media_files and len(rail_sathi_complain_media_files) > 0:
            print(f"Processing {len(rail_sathi_complain_media_files)} files")
            
            # Read all file contents first (before threading)
            file_data_list = []
            for file_obj in rail_sathi_complain_media_files:
                if file_obj.filename:  # Check if file is actually uploaded
                    file_content = await file_obj.read()
                    file_data_list.append({
                        'content': file_content,
                        'filename': file_obj.filename,
                        'content_type': file_obj.content_type
                    })
                    print(f"Read file: {file_obj.filename}, size: {len(file_content)}")
            
            # Process files in threads
            threads = []
            for file_data in file_data_list:
                # Create a mock file object for threading
                class MockFile:
                    def __init__(self, content, filename, content_type):
                        self.content = content
                        self.filename = filename
                        self.content_type = content_type
                    
                    def read(self):
                        return self.content
                
                mock_file = MockFile(file_data['content'], file_data['filename'], file_data['content_type'])
                t = threading.Thread(
                    target=upload_file_thread, 
                    args=(mock_file, complain_id, name or ''),
                    name=f"FileUpload-{complain_id}-{file_data['filename']}"
                )
                t.start()
                threads.append(t)
                print(f"Started thread for file: {file_data['filename']}")
            
            # Wait for all threads to complete
            for t in threads:
                t.join()
                print(f"Thread completed: {t.name}")
        
        # Add a small delay to ensure database operations complete
        await asyncio.sleep(1)
        
        # Get final updated complaint with media files
        final_complaint = get_complaint_by_id(complain_id)
        #ensure customer_care exists
        if "customer_care" not in final_complaint:
           final_complaint["customer_care"] = None
        print(f"Final complaint data retrieved with {len(final_complaint.get('rail_sathi_complain_media_files', []))} media files")
        
        return {
            "message": "Complaint updated successfully",
            "data": final_complaint
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating complaint {complain_id}: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.put("/complaint/update/{complain_id}", response_model=RailSathiComplainResponse)
async def replace_complaint_endpoint(
    complain_id: int,
    current_user: dict = Depends(get_current_user),

    pnr_number: Optional[str] = Form(None),
    is_pnr_validated: str = Form("not-attempted"),
    name: Optional[str] = Form(None),
    mobile_number: Optional[str] = Form(None),
    complain_type: Optional[str] = Form(None),
    complain_description: Optional[str] = Form(None),
    complain_date: Optional[str] = Form(None),
    complain_status: str = Form("pending"),
    train_id: Optional[int] = Form(None),
    train_number: Optional[str] = Form(None),
    train_name: Optional[str] = Form(None),
    coach: Optional[str] = Form(None),
    berth_no: Optional[int] = Form(None),
    rail_sathi_complain_media_files: List[UploadFile] = File(default=[])
):
    """Replace complaint (full update)"""
    try:
        print(f"Replacing complaint {complain_id} for user: {name}")
        print(f"Number of files received: {len(rail_sathi_complain_media_files)}")
        
        # Check if complaint exists and validate permissions
        existing_complaint = get_complaint_by_id(complain_id)
        if not existing_complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")
        
        username = current_user["username"]

        # Check permissions
        if (existing_complaint["created_by"] != username or 
            existing_complaint["complain_status"] == "completed"):
            raise HTTPException(status_code=403, detail="Only user who created the complaint can update it.")
        
        # Prepare full update data
        update_data = {
            "pnr_number": pnr_number,
            "is_pnr_validated": is_pnr_validated,
            "name": name,
            "mobile_number": mobile_number,
            "complain_type": complain_type,
            "complain_description": complain_description,
            "complain_date": complain_date,
            "complain_status": complain_status,
            "train_id": train_id,
            "train_number": train_number,
            "train_name": train_name,
            "coach": coach,
            "berth_no": berth_no,
            "updated_by": username
        }
        
        # Update complaint
        updated_complaint = update_complaint(complain_id, update_data)
        print(f"Complaint {complain_id} replaced successfully")
        
        # Handle file uploads if any files are provided
        if rail_sathi_complain_media_files and len(rail_sathi_complain_media_files) > 0:
            print(f"Processing {len(rail_sathi_complain_media_files)} files")
            
            # Read all file contents first (before threading)
            file_data_list = []
            for file_obj in rail_sathi_complain_media_files:
                if file_obj.filename:  # Check if file is actually uploaded
                    file_content = await file_obj.read()
                    file_data_list.append({
                        'content': file_content,
                        'filename': file_obj.filename,
                        'content_type': file_obj.content_type
                    })
                    print(f"Read file: {file_obj.filename}, size: {len(file_content)}")
            
            # Process files in threads
            threads = []
            for file_data in file_data_list:
                # Create a mock file object for threading
                class MockFile:
                    def __init__(self, content, filename, content_type):
                        self.content = content
                        self.filename = filename
                        self.content_type = content_type
                    
                    def read(self):
                        return self.content
                
                mock_file = MockFile(file_data['content'], file_data['filename'], file_data['content_type'])
                t = threading.Thread(
                    target=upload_file_thread, 
                    args=(mock_file, complain_id, name or ''),
                    name=f"FileUpload-{complain_id}-{file_data['filename']}"
                )
                t.start()
                threads.append(t)
                print(f"Started thread for file: {file_data['filename']}")
            
            # Wait for all threads to complete
            for t in threads:
                t.join()
                print(f"Thread completed: {t.name}")
        
        # Add a small delay to ensure database operations complete
        await asyncio.sleep(1)
        
        # Get final updated complaint with media files
        final_complaint = get_complaint_by_id(complain_id)
        print(f"Final complaint data retrieved with {len(final_complaint.get('rail_sathi_complain_media_files', []))} media files")
        if "customer_care" not in final_complaint:
           final_complaint["customer_care"] = None
        # Return properly formatted response (this was the missing part!)
        return {
            "message": "Complaint replaced successfully",
            "data": final_complaint
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error replacing complaint {complain_id}: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.delete("/complaint/delete/{complain_id}")
async def delete_complaint_endpoint(
    complain_id: int,
    name: str = Form(...),
    mobile_number: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Delete complaint"""
    try:
        print(f"Deleting complaint {complain_id} for user: {name}")
        
        # Check if complaint exists and validate permissions
        existing_complaint = get_complaint_by_id(complain_id)
        if not existing_complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")
        
        username = current_user["username"]

        # Check permissions
        if (existing_complaint["created_by"] != username or 
            existing_complaint["complain_status"] == "completed" or 
            existing_complaint["mobile_number"] != mobile_number):
            raise HTTPException(status_code=403, detail="Only user who created the complaint can delete it.")
        
        # Delete complaint
        delete_complaint(complain_id)
        print(f"Complaint {complain_id} deleted successfully")
        
        return {"message": "Complaint deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting complaint {complain_id}: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.delete("/media/delete/{complain_id}")
async def delete_complaint_media_endpoint(
    complain_id: int,
    name: str = Form(...),
    mobile_number: str = Form(...),
    deleted_media_ids: List[int] = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Delete complaint media files"""
    try:
        print(f"Deleting media files for complaint {complain_id} for user: {name}")
        print(f"Media IDs to delete: {deleted_media_ids}")
        
        # Check if complaint exists and validate permissions
        existing_complaint = get_complaint_by_id(complain_id)
        if not existing_complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")
        
        # Check permissions
        if (existing_complaint["created_by"] != name or 
            existing_complaint["complain_status"] == "completed" or 
            existing_complaint["mobile_number"] != mobile_number):
            raise HTTPException(status_code=403, detail="Only user who created the complaint can update it.")
        
        if not deleted_media_ids:
            raise HTTPException(status_code=400, detail="No media IDs provided for deletion.")
        
        # Delete media files
        deleted_count = delete_complaint_media(complain_id, deleted_media_ids)
        
        if deleted_count == 0:
            raise HTTPException(status_code=400, detail="No matching media files found for deletion.")
        
        print(f"{deleted_count} media file(s) deleted successfully for complaint {complain_id}")
        
        return {"message": f"{deleted_count} media file(s) deleted successfully."}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting complaint media {complain_id}: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    

def make_json_serializable(data):
    if isinstance(data, dict):
        return {k: make_json_serializable(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [make_json_serializable(i) for i in data]
    elif isinstance(data, (time, date, datetime)):
        return data.isoformat()
    else:
        return data