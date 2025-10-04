from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends ,Request,Security
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


app = FastAPI(
    title="Rail Sathi Complaint API",
    description="API for handling rail complaints",
    version="1.0.0",
    openapi_url="/rs_microservice/openapi.json",  # Add the prefix here
    docs_url="/rs_microservice/docs",             # Add the prefix here
    redoc_url="/rs_microservice/redoc"            # Add the prefix here (optional)
)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from database import get_db_connection
from psycopg2.extras import RealDictCursor


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/rs_microservice")
async def root():
    return {"message": "Rail Sathi Microservice is running"}


class RailSathiComplainMediaResponse(BaseModel):
    id: int
    media_type: Optional[str]
    media_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    updated_by: Optional[str]

# Separate the complaint data model
class RailSathiComplainData(BaseModel):
    complain_id: int
    pnr_number: Optional[str]
    is_pnr_validated: Optional[str]
    name: Optional[str]
    mobile_number: Optional[str]
    complain_type: Optional[str]
    complain_description: Optional[str]
    complain_date: Optional[date]
    complain_status: str
    train_id: Optional[int]
    train_number: Optional[str]
    train_name: Optional[str]
    coach: Optional[str]
    berth_no: Optional[int]
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime
    updated_by: Optional[str]
    # Add the missing fields from your actual data
    customer_care: Optional[str]
    train_depot: Optional[str]
    rail_sathi_complain_media_files: List[RailSathiComplainMediaResponse]
    
class RailSathiComplainGetData(BaseModel):
    complain_id: int
    pnr_number: Optional[str]
    is_pnr_validated: Optional[str]
    name: Optional[str]
    mobile_number: Optional[str]
    complain_type: Optional[str]
    complain_description: Optional[str]
    complain_date: Optional[date]
    complain_status: str
    train_id: Optional[int]
    train_number: Optional[str]
    train_name: Optional[str]
    coach: Optional[str]
    berth_no: Optional[int]
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime
    updated_by: Optional[str]
    train_depot: Optional[str]
    rail_sathi_complain_media_files: List[RailSathiComplainMediaResponse]


# Response wrapper that matches your actual API response structure
class RailSathiComplainResponse(BaseModel):
    message: str
    data: RailSathiComplainGetData

# Alternative: If you want to keep the flat structure, modify your endpoint to return:
class RailSathiComplainFlatResponse(BaseModel):
    message: str
    complain_id: int
    pnr_number: Optional[str]
    is_pnr_validated: Optional[str]
    name: Optional[str]
    mobile_number: Optional[str]
    complain_type: Optional[str]
    complain_description: Optional[str]
    complain_date: Optional[date]
    complain_status: str
    train_id: Optional[int]
    train_number: Optional[str]
    train_name: Optional[str]
    coach: Optional[str]
    berth_no: Optional[int]
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime
    updated_by: Optional[str]
    rail_sathi_complain_media_files: List[RailSathiComplainMediaResponse]

@app.get("/rs_microservice/complaint/get/{complain_id}", response_model=RailSathiComplainResponse)
async def get_complaint(complain_id: int):
    """Get complaint by ID"""
    try:
        complaint = get_complaint_by_id(complain_id)
        if not complaint:
            logger.error(f"Complaint {complain_id} not found")
            raise HTTPException(status_code=404, detail="Complaint not found")
        
        # Wrap the complaint in the expected response format
        return RailSathiComplainResponse(
            message="Complaint retrieved successfully",
            data=complaint
        )
    except HTTPException as e:
        raise e

    except Exception as e:
        logger.error(f"Error getting complaint {complain_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/rs_microservice/complaint/get/date/{date_str}", response_model=List[RailSathiComplainResponse])
async def get_complaints_by_date_endpoint(date_str: str, mobile_number: Optional[str] = None):
    """Get complaints by date and mobile number"""
    try:
        # Validate date format
        try:
            complaint_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
        
        if not mobile_number:
            raise HTTPException(status_code=400, detail="mobile_number parameter is required")
        
        # Validate mobile number format if needed
        if not mobile_number.strip():
            raise HTTPException(status_code=400, detail="mobile_number cannot be empty")
        
        complaints = get_complaints_by_date(complaint_date, mobile_number)
        
        # Handle empty results
        if not complaints:
            return []
        
        # Wrap each complaint in the expected response format
        response_list = []
        for complaint in complaints:
            try:
                # Ensure all required fields are present for RailSathiComplainResponse
                if 'customer_care' not in complaint:
                    complaint['customer_care'] = None
                
                response_list.append(RailSathiComplainResponse(
                    message="Complaint retrieved successfully",
                    data=complaint
                ))
            except Exception as validation_error:
                logger.error(f"Error creating response for complaint: {str(validation_error)}")
                logger.error(f"Complaint data: {complaint}")
                # Add the missing field and try again
                try:
                    complaint['customer_care'] = None
                    response_list.append(RailSathiComplainResponse(
                        message="Complaint retrieved successfully",
                        data=complaint
                    ))
                except Exception as retry_error:
                    logger.error(f"Retry failed for complaint {complaint.get('complain_id')}: {str(retry_error)}")
                    # Continue with other complaints rather than failing completely
                    continue
        
        return response_list
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting complaints by date {date_str} for mobile {mobile_number}: {str(e)}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/rs_microservice/complaint/add", response_model=RailSathiComplainResponse)
@app.post("/rs_microservice/complaint/add/", response_model=RailSathiComplainResponse)
async def create_complaint_endpoint_threaded(
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
            "created_by": name
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


@app.patch("/rs_microservice/complaint/update/{complain_id}", response_model=RailSathiComplainResponse)
async def update_complaint_endpoint(
    complain_id: int,
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

        existing_complaint = get_complaint_by_id(complain_id)
        if not existing_complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")

        # Prepare update data
        update_data = {
            "submission_status": "submitted",  # ✅ Always set on update
            "updated_by": name
        }
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

        # Update DB
        update_complaint(complain_id, update_data)
        print(f"Complaint {complain_id} updated successfully")

        # Upload media files
        if rail_sathi_complain_media_files:
            file_data_list = []
            for file_obj in rail_sathi_complain_media_files:
                if file_obj.filename:
                    content = await file_obj.read()
                    file_data_list.append({
                        "content": content,
                        "filename": file_obj.filename,
                        "content_type": file_obj.content_type
                    })
            threads = []
            for file in file_data_list:
                class MockFile:
                    def __init__(self, content, filename, content_type):
                        self.content = content
                        self.filename = filename
                        self.content_type = content_type
                    def read(self):
                        return self.content
                mock_file = MockFile(file["content"], file["filename"], file["content_type"])
                t = threading.Thread(
                    target=upload_file_thread,
                    args=(mock_file, complain_id, name or ''),
                    name=f"FileUpload-{complain_id}-{file['filename']}"
                )
                t.start()
                threads.append(t)
            for t in threads:
                t.join()

        await asyncio.sleep(1)  # Ensure file threads complete

        # ✅ Final enriched response just like POST
        final_complaint = await enrich_complaint_response_and_trigger_email(
            complain_id=complain_id,
            pnr_number=pnr_number or existing_complaint.get("pnr_number"),
            train_number=train_number or existing_complaint.get("train_number"),
            coach=coach or existing_complaint.get("coach"),
            berth_no=berth_no or existing_complaint.get("berth_no"),
            date_of_journey=complain_date or existing_complaint.get("complain_date")
        )

        return {
            "message": "Complaint updated successfully",
            "data": final_complaint
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating complaint {complain_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.put("/rs_microservice/complaint/update/{complain_id}", response_model=RailSathiComplainResponse)
async def replace_complaint_endpoint(
    complain_id: int,
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
        
        # Check permissions
        if (existing_complaint["created_by"] != name or 
            existing_complaint["complain_status"] == "completed" or 
            existing_complaint["mobile_number"] != mobile_number):
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
            "updated_by": name
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

@app.delete("/rs_microservice/complaint/delete/{complain_id}")
async def delete_complaint_endpoint(
    complain_id: int,
    name: str = Form(...),
    mobile_number: str = Form(...)
):
    """Delete complaint"""
    try:
        print(f"Deleting complaint {complain_id} for user: {name}")
        
        # Check if complaint exists and validate permissions
        existing_complaint = get_complaint_by_id(complain_id)
        if not existing_complaint:
            raise HTTPException(status_code=404, detail="Complaint not found")
        
        # Check permissions
        if (existing_complaint["created_by"] != name or 
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

@app.delete("/rs_microservice/media/delete/{complain_id}")
async def delete_complaint_media_endpoint(
    complain_id: int,
    name: str = Form(...),
    mobile_number: str = Form(...),
    deleted_media_ids: List[int] = Form(...)
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

@app.get("/rs_microservice/train_details/{train_no}")
def get_train_details(train_no: str):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM trains_traindetails WHERE train_no = %s", (train_no,))
        train_detail = cursor.fetchone()

        if not train_detail:
            return JSONResponse(content={"error": "Train not found"}, status_code=404)

        depot_code = train_detail.get('Depot')
        cursor.execute("SELECT * FROM station_Depot WHERE depot_code = %s", (depot_code,))
        depot = cursor.fetchone()

        if depot:
            division_code = depot.get("division_id")
            cursor.execute("SELECT * FROM station_division WHERE division_id = %s", (division_code,))
            division = cursor.fetchone()

            zone_code = None
            if division:
                zone_id = division.get("zone_id")
                cursor.execute("SELECT * FROM station_zone WHERE zone_id = %s", (zone_id,))
                zone = cursor.fetchone()
                zone_code = zone.get("zone_code") if zone else None

            extra_info = {
                "depot_code": depot.get("depot_code"),
                "division_code": division.get("division_code") if division else None,
                "zone_code": zone_code,
            }
        else:
            extra_info = {
                "depot_code": None,
                "division_code": None,
                "zone_code": None,
            }

        train_detail['extra_info'] = extra_info

        # ✅ Convert to JSON-safe format before returning
        safe_train_detail = make_json_serializable(train_detail)
        return JSONResponse(content=safe_train_detail)

    finally:
        cursor.close()
        conn.close()
    
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

async def enrich_complaint_response_and_trigger_email(
    complain_id: int,
    pnr_number: Optional[str],
    train_number: Optional[str],
    coach: Optional[str],
    berth_no: Optional[int],
    date_of_journey: Optional[str],
) -> dict:
    train_depot_name = ''
    war_room_phone = ''
    
    # Step 1: Get depot info
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
            logger.error(f"Error fetching depot: {str(e)}")
        finally:
            conn.close()

    # Step 2: Get WRUR
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
            result = execute_query(conn, war_room_user_query)
            war_room_phone = result[0]['phone'] if result else ''
        except Exception as e:
            logger.error(f"Error fetching WRUR: {str(e)}")
        finally:
            conn.close()

    # Step 3: Send fallback email if WRUR not found
    if not war_room_phone:
        war_room_phone = "9123183988"
        env = os.getenv("ENV")
        subject = f"{env or 'LOCAL'} | {train_number} ({train_depot_name}) No War Room User RailSathi(WRUR) Found !"
        message = f"""
No War Room User RailSathi (WRUR) exists for PNR Number: {pnr_number} in Train Number: {train_number} 
Coach/Berth: {coach}/{berth_no} on {date_of_journey}
Train Depot: {train_depot_name}

Kindly verify the WRUR assignment to the given train depot.
"""
        send_plain_mail(
            subject=subject,
            message=message,
            from_=os.getenv("MAIL_FROM"),
            to=["contact@suvidhaen.com"]
        )

    # Step 4: Fetch final complaint data with media
    final_data = get_complaint_by_id(complain_id)
    final_data["customer_care"] = war_room_phone
    final_data["train_depot"] = train_depot_name
    return final_data

from fastapi import FastAPI
from auth_api_services import router as auth_router
app.include_router(auth_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5002)

