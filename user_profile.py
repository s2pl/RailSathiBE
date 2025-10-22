from database import execute_query, get_db_connection
from pydantic import BaseModel, EmailStr, Field
from fastapi import HTTPException, Depends, APIRouter
from passlib.hash import django_pbkdf2_sha256
from passlib.context import CryptContext
import logging
from datetime import datetime, date, time , timedelta, timezone
from utils.email_utils import send_plain_mail
import random, uuid, re, os, requests, time
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from psycopg2.extras import RealDictCursor
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from typing import List, Optional
from fastapi_limiter.depends import RateLimiter
from dateutil.parser import parse



pwd_context = CryptContext(schemes=["django_pbkdf2_sha256"], deprecated="auto")

router = APIRouter(prefix="/rs_microservice/v2", tags=["RailSathi User Profile"])

# Initialize password context for hashing
pwd_context = CryptContext(schemes=["django_pbkdf2_sha256"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/rs_microservice/v2/token")

#JWT configuration
SECRET_KEY = os.getenv("SECRET_KEY","fallback_dummy_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
API_KEY = os.getenv("TWO_FACTOR_API_KEY", "DUMMY_API_KEY")

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))  # short-lived
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))      # long-lived
ENVIRONMENT = os.getenv("ENVIRONMENT", "LOCAL").upper()

MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
MAIL_FROM=os.getenv("MAIL_FROM"),
MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
MAIL_SERVER=os.getenv("MAIL_SERVER"),
MAIL_TLS=os.getenv("MAIL_TLS", "True") == "True",
MAIL_SSL=os.getenv("MAIL_SSL", "False") == "True",
USE_CREDENTIALS=True,


timestamp = datetime.utcnow()

blacklisted_tokens = set()


#JWT token generator
def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict, expires_delta: timedelta = timedelta(days=7)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

if ENVIRONMENT == "LOCAL":
    def RateLimiter(times: int, seconds: int):
        async def dependency():
            return
        return Depends(dependency)
else:
    from fastapi_limiter.depends import RateLimiter


#Login Endpoint to get JWT token
@router.post("/token")
async def token_generation(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint to get JWT token
    **created by - Asad Khan**

    **created on - 08 aug 2025**
    """
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
        
        user_data = {"sub": user[0]['username'],
}
        access_token = create_access_token(user_data, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        refresh_token = create_refresh_token(user_data, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

        return {"access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer"}
    
    except HTTPException:
        raise
    finally:
        conn.close()

def is_token_blacklisted(token: str):
    return token in blacklisted_tokens

#User authentication Dependecy
def get_current_user(token: str = Depends(oauth2_scheme)):
    """Check JWT token in Authorization header"""

    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=401,
            detail="Token has been revoked or logged out"
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        print("Decoded payload:", payload)

        username: str = payload.get("user_id") or payload.get("sub")

        if not username:
            raise HTTPException(
                status_code=401,
                detail="Invalid token"
                )
        return{"username": username}
    except JWTError as e:
        print("JWT decode error:", e)
        raise HTTPException(
                status_code=401,
                detail="Invalid or expired token"
            )

class SignupRequest(BaseModel):
    username: str
    phone: str
    password: str

@router.post("/signup")
async def signup(data: SignupRequest):
    """
    **created by - Asad Khan**

    **created on - 29 sep 2025**
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # -----------------------------
        # Normalize input
        # -----------------------------
        data.username = data.username.strip().lower()
        data.phone = data.phone.strip()

        # -----------------------------
        # Required fields validation
        # -----------------------------
        required_fields = ["username", "phone", "password"]
        for field in required_fields:
            if not getattr(data, field):
                raise HTTPException(status_code=400, detail=f"{field} is required")

        # -----------------------------
        # Phone Validation
        # -----------------------------
        if not re.match(r'^[1-9]\d{9}$', data.phone):
            raise HTTPException(status_code=400, detail="Invalid phone number")
        
        # -----------------------------
        # Duplicate checks
        # -----------------------------
        cur.execute("""
            SELECT id FROM user_onboarding_user
            WHERE phone=%s OR username=%s
        """, (data.phone, data.username))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="User already exists")
        
        # -----------------------------
        # Password Hashing
        # -----------------------------
        hashed_password = django_pbkdf2_sha256.hash(data.password)

        # -----------------------------
        # Generate fallback value for email as email is mandatory and unique field in user table
        # -----------------------------
        email = f"noemail.{data.phone}@gmail.com"
        now = datetime.now(timezone.utc)

        # -----------------------------
        # Insert new user
        # -----------------------------

        cur.execute("""
            INSERT INTO user_onboarding_user
            (first_name,last_name, username, email, phone, password,
             created_at, created_by, updated_at, updated_by, is_active, staff, railway_admin, enabled,
             user_type_id, user_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,FALSE,FALSE,TRUE,1,'active')
            RETURNING id, username, phone, email
        """, (data.username, '', data.username, email, data.phone, hashed_password, now, data.username, now, data.username))

        new_user = cur.fetchone()
        conn.commit()
        return JSONResponse(
            status_code=201,
            content= {
                "message": "Passenger registered successfully",
                "user": new_user
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error during signup")
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")
    finally:
        conn.close()


class SigninRequest(BaseModel):
    phone: str
    password: str
@router.post("/signin")
async def signin(data: SigninRequest):
    """
    Signin endpoint using mobile number and password.
    Returns JWT token if credentials are correct.

    **created by - Asad Khan**

    **created on - 29 sep 2025**
    """
    conn = get_db_connection()

    try:
        # Fetch user by phone number
        user_list = execute_query(
            conn,
            "SELECT * FROM user_onboarding_user WHERE phone = %s",
            (data.phone,)
        )

        if not user_list:
            raise HTTPException(status_code=401, detail="User not found or invalid credentials")

        user = user_list[0]

        # Verify password
        if not django_pbkdf2_sha256.verify(data.password, user['password']):
            raise HTTPException(status_code=401, detail="Incorrect password")

        # Generate JWT token
        refresh_token = create_refresh_token(data={"sub": user['username']})
        access_token = create_access_token(data={"sub": user['username']})

        return JSONResponse({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": user['first_name'],
            "number": user['phone'],
            "Whatsapp_number": user['whatsapp_number'],
            "email": user['email'],
            "created_at": user['created_at'],
            "token_type": "bearer"
        })
    except HTTPException:
        raise
    finally:
        conn.close()



@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    """
    Logout endpoint - blacklists the provided JWT token.
    """
    blacklisted_tokens.add(token)
    return ({"message": "Logged out successfully."})

# -----------------------------
# Pydantic Schemas
# -----------------------------
class OTPRequest(BaseModel):
    phone_number: str
    fcm_token: Optional[str] = None


class OTPVerifyRequest(BaseModel):
    to: str
    otp_code: str
    fcm_token: Optional[str] = None

# -----------------------------
# OTP Functions
# -----------------------------
def send_otp(to, template_name) -> Optional[str]:
    number = f"+91{to}"
    url = f"https://2factor.in/API/V1/{API_KEY}/SMS/{number}/AUTOGEN/{template_name}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("Status") == "Success":
            session_id = data.get("Details")
            return session_id
        else:
            logging.warning(f"2Factor OTP failed for {to}: {data.get('Details')}")
            return None
    except requests.RequestException as e:
        logging.exception(f"Exception sending OTP to {to}: {e}")
        return None


def verify_otp(session_id: str, otp_code: str) -> bool:
    url = f"https://2factor.in/API/V1/{API_KEY}/SMS/VERIFY/{session_id}/{otp_code}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        return data.get("Status") == "Success" and data.get("Details") == "OTP Matched"
    except requests.RequestException as e:
        logging.exception(f"Exception verifying OTP session {session_id}: {e}")
        return False


# -----------------------------
# Routes
# -----------------------------
@router.post("/mobile-login/request-otp", dependencies=[RateLimiter(times=10, seconds=60)])
async def login_otp_send(data: OTPRequest):
    """
    **created by - Asad Khan**

    **created on - 11 oct 2025**

    fcm token in Optional
    """
    TEMPLATE_NAME = "Login+via+OTP"
    to = data.phone_number.strip()

    if not to.isdigit() or len(to) != 10:
        raise HTTPException(status_code=400, detail="Phone number must be exactly 10 digits")
    
    conn = get_db_connection()

    user = execute_query(
        conn,
        "SELECT * FROM user_onboarding_user WHERE phone = %s",
        (data.phone_number,)
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user[0]

    # Check user status
    if user_data['user_status'] in {"disabled", "suspended", "blocked"}:
        raise HTTPException(status_code=400, detail=f"User is {user_data['user_status']}")

    now = datetime.now()

    # Send OTP via 2Factor
    session_id = send_otp(to, TEMPLATE_NAME)
    if session_id:
        execute_query(
            conn,
            """INSERT INTO user_onboarding_otp (phone, otp, session_id, counter, created_at, timestamp, created_by, updated_at, updated_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (to, '', session_id, 0, now, now, 0, now, 0)
        )
        conn.commit()
        return JSONResponse(status_code=200, content={"detail": "OTP sent successfully."})
    else:
        error_message = "Failed to send OTP request. Please check your number."
        raise HTTPException(status_code=400, detail=error_message)

    return {"message": "OTP sent successfully. Please check your phone."}

@router.post("/mobile-login/verify-otp", dependencies=[RateLimiter(times=10, seconds=60)])
async def login_otp_verify(data: OTPVerifyRequest):
    """
    **created by - Asad Khan**

    **created on - 11 oct 2025**

    fcm token is Optional
    """
    phone = data.to.strip()
    otp_code = data.otp_code.strip()

    if len(otp_code) != 6:
        raise HTTPException(status_code=400, detail="OTP length should be 6")
    
    conn = get_db_connection()

    otp_obj = execute_query(
        conn,
        "SELECT * FROM user_onboarding_otp WHERE phone = %s ORDER BY created_at DESC LIMIT 1",
        (phone,)
    )
    if not otp_obj:
        raise HTTPException(status_code=404, detail="OTP not found. Please generate a new OTP.")

    otp_data = otp_obj[0]
    created_at = parse(otp_data['created_at'])

    now_utc = datetime.now(timezone.utc)

    # Expiry and retry check
    if now_utc > created_at + timedelta(minutes=10) or otp_data['counter'] >= 5:
        execute_query(
            conn,
            "DELETE FROM user_onboarding_otp WHERE id = %s",
            (otp_data['id'],)
        )
        conn.commit()
        raise HTTPException(status_code=400, detail="OTP has expired. Please generate a new OTP.")

    # Verify otp
    if not verify_otp(otp_data['session_id'], otp_code):
        execute_query(
            conn,
            "UPDATE user_onboarding_otp SET counter = counter + 1 WHERE id = %s",
            (otp_data['id'],)
        )
        conn.commit()
        raise HTTPException(status_code=400, detail="Incorrect OTP")

    # OTP correct
    user_data = execute_query(
        conn,
        "SELECT * FROM user_onboarding_user WHERE phone = %s",
        (phone,)
    )
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    user = user_data[0]
    timestamp = datetime.utcnow()

    # Save FCM token if provided
    if data.fcm_token:
        execute_query(
            conn,
            "UPDATE user_onboarding_user SET fcm_token=%s, updated_at=NOW() WHERE id=%s",
            (data.fcm_token, user['id'],)
        )
        conn.commit()

    # Login history
    login_history = execute_query(
        conn,
        "SELECT * FROM user_onboarding_loginhistory WHERE user_id = %s ORDER BY last_login DESC LIMIT 1",
        (user['id'],)
    )
    if not login_history:
        execute_query(
            conn,
            "INSERT INTO user_onboarding_loginhistory (user_id, last_login) VALUES (%s, %s)",
            (user['id'], timestamp)
        )
        conn.commit()
    else:
        execute_query(
            conn,
            "UPDATE user_onboarding_loginhistory SET last_login = %s WHERE id = %s",
            (timestamp, login_history[0]['id'])
        )
        conn.commit()

    # JWT tokens
    access_token = create_access_token({"user_id": user['id']})
    refresh_token = create_refresh_token({"user_id": user['id']})

    return JSONResponse({
        "message": "Logged in successfully",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "username": user['username'],
        "number": user['phone'],
        "first_name": user['first_name'],
        "middle_name": user['middle_name'],
        "last_name": user['last_name'],
        "created_at": user['created_at'],
        "token_type": "bearer"
    })

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    re_new_password: str
    otp_code: Optional[str] = Field(..., example="")


@router.post('/change-password')
async def change_password(
    data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """Change password for authenticated user

    **created by - Asad Khan**

    **created on - 11 oct 2025**
    """
    conn = get_db_connection()
    try:
        if not current_user or "username" not in current_user:
            raise HTTPException(status_code=401, detail="User not authenticated")

        username = current_user["username"]

        # Fetch current user details
        user_list = execute_query(
            conn,
            "SELECT * FROM user_onboarding_user WHERE username = %s",
            (username,)
        )
        if not user_list:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = user_list[0]
        phone = user["phone"]

        # Verify old password
        if not django_pbkdf2_sha256.verify(data.old_password, user['password']):
            raise HTTPException(status_code=400, detail="Old password is incorrect")

        if not data.otp_code:
            TEMPLATE_NAME = "Change+Password"
            session_id = send_otp(phone, TEMPLATE_NAME)
            if not session_id:
                raise HTTPException(status_code=400, detail="Failed to send OTP")

            now = datetime.now()
            execute_query(
                conn,
                """INSERT INTO user_onboarding_otp (phone, otp, session_id, counter, created_at, timestamp, created_by, updated_at, updated_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (phone, '', session_id, 0, now, now, 0, now, 0)
            )
            conn.commit()
            logging.info(f"send on user's phone:{phone}")
            return {"message": "OTP sent successfully. Please verify it by sending the same API again with otp_code."}
        
        otp_obj = execute_query(
            conn,
            "SELECT * FROM user_onboarding_otp WHERE phone = %s ORDER BY created_at DESC LIMIT 1",
            (phone,)
        )
        if not otp_obj:
            raise HTTPException(status_code=404, detail="OTP not found. Please request again.")

        otp_data = otp_obj[0]
        if not verify_otp(otp_data["session_id"], data.otp_code.strip()):
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")
        
        # Check new passwords match
        if data.new_password != data.re_new_password:
            raise HTTPException(status_code=400, detail="New passwords do not match")
        
        # Hash new password and update
        hashed_new_password = pwd_context.hash(data.new_password[:72])  # truncate to 72 bytes

        execute_query(
            conn,
            """
            UPDATE user_onboarding_user
            SET password = %s, updated_at = NOW(), updated_by = %s
            WHERE username = %s
            """,
            (hashed_new_password, username, username)
        )
        conn.commit()
        
        execute_query(conn, "DELETE FROM user_onboarding_otp WHERE id = %s", (otp_data["id"],))
        conn.commit()

        return {"message": "Password changed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error changing password")
        raise HTTPException(status_code=500, detail=f"Password change failed: {str(e)}")
    finally:
        conn.close()



class EmailOTPRequest(BaseModel):
    email: EmailStr

class EmailOTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str

@router.post("/send-email-otp") #add email in user profile
async def send_email_otp(data: EmailOTPRequest, current_user: dict = Depends(get_current_user)):
    """ 
    Add Email In User's Profile and for that it needs OTP verification via email

    **created by - Asad Khan**

    **created on - 15 oct 2025**
    """
    conn = get_db_connection()
    try:
        if not current_user or "username" not in current_user:
            raise HTTPException(status_code=401, detail="User not authenticated")

        try:
            validate_email(data.email)
        except ValidationError:
            raise HTTPException(status_code=400, detail="Invalid email")

        #Remove any previous OTP for this email
        execute_query(conn, "DELETE FROM user_onboarding_otp WHERE email = %s;", (data.email,))

        #generate otp and session
        otp = str(random.randint(100000, 999999))
        session_id = str(uuid.uuid4())

        execute_query(
            conn,
            """INSERT INTO user_onboarding_otp
            (email, otp, session_id, counter, timestamp, created_at, created_by, updated_at, updated_by)
            VALUES (%s, %s, %s, %s, NOW(), NOW(), %s, NOW(), %s) RETURNING id;
            """,
            (data.email, otp, session_id, 0, current_user["username"], current_user["username"])
        )
        conn.commit()

        # Send email
        subject = "Your RailSathi Email OTP"
        message = f"""
        Dear User,

        Your OTP for email verification is: {otp}

        This OTP is valid for 10 minutes.
        """

        mail_sent = send_plain_mail(subject, message, from_=os.getenv("MAIL_FROM"), to=[data.email])

        if not mail_sent:
            raise HTTPException(status_code=500, detail="Failed to send OTP email")

        return {"message": "OTP sent successfully", "session_id": session_id}

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error sending email OTP")
        raise HTTPException(status_code=500, detail=f"Email OTP sending failed: {str(e)}")
    finally:
        conn.close()

@router.post("/verify-email-otp")
async def verify_email_otp(data: EmailOTPVerifyRequest, current_user: dict = Depends(get_current_user)):
    """
    Add Email In User's Profile after the verification done
    it added email in user's Profile

    **created by - Asad Khan**

    **created on - 15 oct 2025**
    """
    conn = get_db_connection()
    try:
        if not current_user or "username" not in current_user:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        otp_record = execute_query(
            conn,
            """SELECT otp, timestamp FROM user_onboarding_otp WHERE email = %s ORDER BY timestamp DESC LIMIT 1;
            """,
            (data.email,))
        
        if not otp_record:
            raise HTTPException(status_code=404, detail="OTP record not found. Please request a new OTP.")
        
        otp_data = otp_record[0]
        
        # Handle tuple or dict results safely
        if isinstance(otp_data, dict):
            otp_value = otp_data["otp"]
            otp_timestamp = otp_data["timestamp"]
        else:
            otp_value, otp_timestamp = otp_data

        if isinstance(otp_timestamp, str):
            otp_timestamp = datetime.fromisoformat(otp_timestamp.replace("Z", "+00:00"))

        otp_timestamp = otp_timestamp.replace(tzinfo=timezone.utc) if otp_timestamp.tzinfo is None else otp_timestamp


        now_utc = datetime.now(timezone.utc)
        if otp_value != data.otp:
            raise HTTPException(status_code=400, detail="Incorrect OTP")
        
        if now_utc > otp_timestamp + timedelta(minutes=10):
            raise HTTPException(status_code=400, detail="OTP has expired. Please request a new OTP.")
        
        existing_user = execute_query(
            conn,
            "SELECT id FROM user_onboarding_user WHERE email = %s AND username != %s;",
            (data.email, current_user["username"])
        )

        if existing_user:
            raise HTTPException(status_code=400, detail="Email already exists")

        # Check if the current user already has this email
        user_email_record = execute_query(
            conn,
            "SELECT email FROM user_onboarding_user WHERE username = %s;",
            (current_user["username"],)
        )
        current_email = user_email_record[0]["email"] if user_email_record else None

        if current_email == data.email:
            return {"message": "Email already Exists"}

        # Update otp record
        execute_query(
            conn,
            """UPDATE user_onboarding_otp 
            SET counter = counter + 1, updated_at = NOW(), updated_by = %s WHERE email = %s AND otp = %s;
            """, (current_user['username'], data.email, data.otp)
        )
        conn.commit()

        # Update user's email in user_onboarding_user
        execute_query(
            conn,
            """UPDATE user_onboarding_user 
            SET email = %s , updated_at = NOW(), updated_by = %s
            WHERE username = %s;
            """, (data.email, current_user["username"], current_user["username"])
        )
        conn.commit()

        return {"message": "Email verified and updated successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error during OTP verification")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()