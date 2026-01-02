import email
from database import execute_query, get_db_connection
from pydantic import BaseModel, EmailStr, Field
from fastapi import HTTPException, Depends, APIRouter, status
from passlib.hash import django_pbkdf2_sha256
from passlib.context import CryptContext
import logging, redis
from datetime import datetime, date, time , timedelta, timezone
from utils.email_utils import send_plain_mail, send_email_via_ms
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



router = APIRouter(prefix="/rs_microservice/v2", tags=["RailSathi User Profile"])

# Initialize password context for hashing
pwd_context = CryptContext(schemes=["django_pbkdf2_sha256"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/rs_microservice/v2/token")

#JWT configuration
SECRET_KEY = os.getenv("SECRET_KEY","fallback_dummy_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
API_KEY = os.getenv("TWO_FACTOR_API_KEY", "DUMMY_API_KEY")

ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", 90))  # short-lived
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 180))  # long-lived
ENVIRONMENT = os.getenv("ENVIRONMENT", "LOCAL").upper()

MAIL_USERNAME=os.getenv("MAIL_USERNAME")
MAIL_PASSWORD=os.getenv("MAIL_PASSWORD")
MAIL_FROM=os.getenv("MAIL_FROM")
MAIL_PORT=int(os.getenv("MAIL_PORT", 587))
MAIL_SERVER=os.getenv("MAIL_SERVER")
MAIL_TLS=os.getenv("MAIL_TLS", "True") == "True"
MAIL_SSL=os.getenv("MAIL_SSL", "False") == "True"
USE_CREDENTIALS=True


timestamp = datetime.utcnow()
logger = logging.getLogger(__name__)

blacklisted_tokens: set = set()



#JWT token generator
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

class TokenRefreshRequest(BaseModel):
    refresh_token: str

@router.post("/token/refresh")
async def refresh_token(data: TokenRefreshRequest):
    refresh_token = data.refresh_token
    try:
        if refresh_token in blacklisted_tokens:
            raise HTTPException(status_code=401, detail="Token is blacklisted")

        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        username = payload.get("sub") or payload.get("user_id")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        # generate new access token
        new_access_token = create_access_token({"sub": username})
        new_refresh_token = create_refresh_token({"sub": username})

        blacklisted_tokens.add(refresh_token)

        return {"access_token": new_access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")


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
        user_data = {"sub": user[0]['username'], "phone": user[0]['phone']}
        access_token = create_access_token(user_data)
        refresh_token = create_refresh_token(user_data)

        return {"access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer"}
    
    except HTTPException:
        raise
    finally:
        conn.close()


#User authentication Dependecy
def get_current_user(token: str = Depends(oauth2_scheme)):
    """Check JWT token in Authorization header"""

    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=401,
            detail="Token has been revoked. Please log in again."
        )

    try:
        # Decode token first
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logging.debug(f"Decoded payload: {payload}")
    except JWTError as e:
        logging.exception("JWT decode error")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    # Determine identifier from token (supports both 'sub' (username) and 'user_id')
    token_user_id = payload.get("user_id")
    token_username = payload.get("sub")
    phone = payload.get("phone")

    if not token_user_id and not token_username and not phone:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Fetch user from DB to check status and return authoritative user info
    conn = get_db_connection()
    try:
        if token_user_id:
            user_list = execute_query(conn, "SELECT * FROM user_onboarding_user WHERE id = %s", (token_user_id,))
        else:
            user_list = execute_query(conn, "SELECT * FROM user_onboarding_user WHERE username = %s", (token_username,))

        user = user_list[0] if user_list else None

        if user and user.get("user_status") not in {"enabled"}:
            raise HTTPException(status_code=403, detail="Account is not enabled")

        # Prefer values from DB if available, otherwise fall back to token values
        return {
            "username": user.get("username") if user else token_username or token_user_id,
            "phone": user.get("phone") if user else phone
        }
    finally:
        conn.close()

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

        name_parts = data.username.split()

        first_name = name_parts[0]
        middle_name = None
        last_name = ''

        if len(name_parts) == 2:
            last_name = name_parts[1]
        elif len(name_parts) >= 3:
            middle_name = name_parts[1]
            last_name = " ".join(name_parts[2:])

        final_username = f"{first_name}_{data.phone}"

        # -----------------------------
        # Duplicate checks
        # -----------------------------
        cur.execute("""
            SELECT id, user_status FROM user_onboarding_user
            WHERE phone=%s OR username=%s
        """, (data.phone, final_username))
        existing_user = cur.fetchone()

        if existing_user:
            if existing_user["user_status"] != "enabled":
                raise HTTPException(status_code=400, detail="Account is not enabled. Please contact support to reactivate.")
            else:
                raise HTTPException(status_code=400, detail="User already exists")
        
        # -----------------------------
        # Password Hashing
        # -----------------------------
        hashed_password = pwd_context.hash(data.password)

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
            (first_name, middle_name, last_name, username, email, phone, password,
             created_at, created_by, updated_at, updated_by, is_active, staff, railway_admin, enabled,
             user_type_id, user_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,FALSE,FALSE,TRUE,11,'enabled')
            RETURNING id, username, phone, email
        """, (first_name, middle_name, last_name, final_username, email, data.phone, hashed_password, now, final_username, now, final_username))

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
        
        if user['user_status'] != "enabled":
            raise HTTPException(status_code=400, detail="User account is not enabled. Please contact support to enable the account.")
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


@router.get("/session-check")
async def session_check(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        user = execute_query(
            conn,
            "SELECT * FROM user_onboarding_user WHERE username = %s",
            (current_user["username"],)
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user[0]['user_status'] in {"disabled", "suspended", "blocked"}:
            raise HTTPException(status_code=400, detail=f"User is {user[0]['user_status']}")
        return {"message": "Session is valid", "user": user[0]}
    finally:
        conn.close()


# -------------------------------------------------------------------
# 🧩 Check if token is blacklisted
# -------------------------------------------------------------------
try:
    r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=int(os.getenv("REDIS_DB", 0)),
    decode_responses=True)
    r.ping()
    logging.info("Connected to Redis successfully")
    use_redis = True
except redis.exceptions.ConnectionError:
    logging.warning("Redis connection failed. Using in-memory blacklist instead.")
    r = None
    use_redis = False
    blacklisted_tokens = set()

def is_token_blacklisted(token: str) -> bool:
    if use_redis and r:
        return r.exists(f"bl_{token}")
    else:
        return token in blacklisted_tokens


@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    """
    **created by - Asad Khan**

    **created on - 30 oct 2025**
    """
    try:
        if use_redis and r:
            ttl = 60 * 60 * 24 * 30  # 30 days (same as refresh token expiry)
            r.setex(f"bl_{token}", ttl, "blacklisted")
        else:
            blacklisted_tokens.add(token)
        logging.info(f"Token blacklisted successfully: {token}")
        return {"message": "Logged out successfully"}
    except Exception as e:
        logging.exception("Error during logout", {"exception": str(e)})
        raise HTTPException(status_code=401, detail="Logout failed")


@router.post("/dummy-deactivate-account")
async def dummy_deactivate_account():
    """
    Dummy endpoint for testing account deactivation.
    Always returns 200 OK response.
    """
    return JSONResponse(
        content={"message": "Account successfully deactivated (dummy response)"},
        status_code=status.HTTP_200_OK
    )
class DeactivateAccountRequest(BaseModel):
    phone: str

@router.post("/deactivate/send-otp")
async def send_deactivate_otp(data: DeactivateAccountRequest, current_user: dict = Depends(get_current_user)):
    """Send OTP before deactivation
    
    **created by - Asad Khan**

    **created on - 30 oct 2025**
    """
    phone = data.phone
    user_phone = current_user.get("phone")
    username = current_user.get("username")

    if not phone:
        raise HTTPException(status_code=400, detail="Phone number required")

    if not user_phone or phone != user_phone:
        raise HTTPException(status_code=401, detail="Phone number does not match authenticated user")
    conn = get_db_connection()
    try:
        user_list = execute_query(conn, """
            SELECT id, username, user_status FROM user_onboarding_user WHERE phone = %s
        """, (phone,))
        user = user_list[0] if user_list else None

        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user["user_status"] == "disabled":
            raise HTTPException(status_code=400, detail="Account already deactivated")

        session_id = send_otp(phone, "Deactivate+Account")
        if not session_id:
            raise HTTPException(status_code=500, detail="Failed to send OTP")

        now = datetime.now(timezone.utc)
        execute_query(conn, """
            INSERT INTO user_onboarding_otp (phone, otp, session_id, counter, created_at, timestamp, created_by, updated_at, updated_by)
            VALUES (%s, '', %s, 0, %s, %s, %s, %s, %s)
        """, (phone, session_id, now, now, user["username"], now, user["username"]))

        return {"message": "Deactivation OTP sent successfully", "session_id": session_id}
    except Exception as e:
        logger.error(f"Error during deactivation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    finally:
        conn.close()

class DeactivateOTPVerifyRequest(BaseModel):
    phone: str
    otp: str

@router.post("/deactivate/verify-otp")
async def verify_deactivate_otp(data: DeactivateOTPVerifyRequest, current_user: dict = Depends(get_current_user)):
    """Verify OTP and deactivate account
    
    **created by - Asad Khan**

    **created on - 30 oct 2025**
    """
    phone = data.phone
    otp_code = data.otp
    if not phone or not otp_code:
        raise HTTPException(status_code=400, detail="Phone and OTP required")
    
    user_phone = current_user.get("phone")
    username = current_user.get("username")

    conn = get_db_connection()
    try:
        otp_data = execute_query(conn, """
            SELECT id, session_id, created_at FROM user_onboarding_otp
            WHERE phone = %s ORDER BY created_at DESC LIMIT 1
        """, (phone,))
        if not otp_data:
            raise HTTPException(status_code=404, detail="OTP not found")

        record = otp_data[0]
        if not verify_otp(record["session_id"], otp_code):
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")

        execute_query(conn, """
            UPDATE user_onboarding_user
            SET user_status = 'disabled', updated_at = NOW()
            WHERE phone = %s
        """, (phone,))

        return {"message": "Account successfully deactivated"}
    except Exception as e:
        logger.error(f"Error during deactivation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    finally:
        conn.close()



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

        raise HTTPException(status_code=400, detail="OTP has expired. Please generate a new OTP.")

    # Verify otp
    if not verify_otp(otp_data['session_id'], otp_code):
        execute_query(
            conn,
            "UPDATE user_onboarding_otp SET counter = counter + 1 WHERE id = %s",
            (otp_data['id'],)
        )

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

    else:
        execute_query(
            conn,
            "UPDATE user_onboarding_loginhistory SET last_login = %s WHERE id = %s",
            (timestamp, login_history[0]['id'])
        )

    if user['user_status'] in {"disabled", "suspended", "blocked"}:
        raise HTTPException(status_code=400, detail=f"User is {user['user_status']}")


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
        
        execute_query(conn, "DELETE FROM user_onboarding_otp WHERE id = %s", (otp_data["id"],))


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


        # Send email
        subject = "Your RailSathi Email OTP"
        context = {
            "otp": otp,
            "subject": subject,
            "product_name": "RailSathi"
        }
        
        # Try sending via MS first
        if not send_email_via_ms(data.email, "railsathi/email_otp_verification.txt", context):
            # Fallback to Django
            message = f"""
        Dear User,

        Your OTP for email verification is: {otp}

        This OTP is valid for 10 minutes.
        """
            mail_sent = send_plain_mail(subject, message, from_=os.getenv("MAIL_FROM"), to=[data.email])
            logging.info("Email sent via Django fallback")
            
            if not mail_sent:
                raise HTTPException(status_code=500, detail="Failed to send OTP email")
        else:
            logging.info("Email sent via MS")

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


        # Update user's email in user_onboarding_user
        execute_query(
            conn,
            """UPDATE user_onboarding_user 
            SET email = %s , updated_at = NOW(), updated_by = %s
            WHERE username = %s;
            """, (data.email, current_user["username"], current_user["username"])
        )

        return {"message": "Email verified and updated successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error during OTP verification")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

class MobileNumberRequest(BaseModel):
    mobile_number: str

class ChangeMobileNumberVerifyOTP(BaseModel):
    mobile_number: str
    otp_code: str

OTP_EXPIRY_MINUTES = 5  # adjust as needed


@router.post("/change-mobile-number-request-otp")
async def change_mobile_number_request(
    data: MobileNumberRequest,
    current_user: dict = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        new_phone = data.mobile_number.strip()

        # Validation
        if not re.match(r'^\d{10}$', new_phone):
            raise HTTPException(400, "Phone number must be exactly 10 digits")

        # Check if number already exists for ANY user
        exists = execute_query(
            conn,
            "SELECT id FROM user_onboarding_user WHERE phone = %s",
            (new_phone,)
        )
        if exists:
            raise HTTPException(400, "Phone number already linked with another account")

        TEMPLATE = "Changing+Mobile+Number"

        # Send OTP → returns session_id
        session_id = send_otp(new_phone, TEMPLATE)
        if not session_id:
            raise HTTPException(500, "Failed to send OTP")

        now = datetime.now(timezone.utc)

        # Store OTP session
        execute_query(
            conn,
            """
            INSERT INTO user_onboarding_otp 
                (phone, otp, session_id, counter, created_at, timestamp, created_by, updated_at, updated_by)
            VALUES 
                (%s, %s, %s, 0, %s, %s, %s, %s, %s)
            """,
            (new_phone, '', session_id, now, now, current_user["username"], now, current_user["username"])
        )
        conn.commit()

        return {"message": "OTP sent successfully"}

    except Exception as e:
        logging.exception(f"CHANGE MOBILE VERIFY ERROR: {e}")
        raise

    finally:
        conn.close()



@router.post("/change-mobile-number-verify-otp")
async def change_mobile_number_verify(
    data: ChangeMobileNumberVerifyOTP,
    current_user: dict = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        if not current_user:
            raise HTTPException(401, "User not authenticated")

        new_phone = data.mobile_number.strip()
        typed_otp = data.otp_code.strip()

        # Validate new phone format
        if not re.match(r'^\d{10}$', new_phone):
            raise HTTPException(400, "Phone number must be 10 digits")

        # Load latest OTP session for this number
        otp_row = execute_query(
            conn,
            "SELECT * FROM user_onboarding_otp WHERE phone=%s ORDER BY id DESC LIMIT 1",
            (new_phone,)
        )

        if not otp_row:
            raise HTTPException(400, "OTP not found. Please request again.")

        session_id = otp_row[0]["session_id"]
        print(f"Session ID: {session_id}")

        created_at = parse(otp_row[0]["created_at"])
        if datetime.now(timezone.utc) - created_at > timedelta(minutes=OTP_EXPIRY_MINUTES):
            execute_query(conn, "DELETE FROM user_onboarding_otp WHERE phone=%s", (new_phone,))
            conn.commit()
            raise HTTPException(400, "OTP expired. Request a new one.")

        if not verify_otp(session_id, typed_otp):
            raise HTTPException(400, "Invalid OTP")

        execute_query(
            conn,
            """
            UPDATE user_onboarding_user
            SET phone=%s, updated_at=NOW(), updated_by=%s
            WHERE username=%s
            """,
            (new_phone, current_user["username"], current_user["username"])
        )

        execute_query(conn, "DELETE FROM user_onboarding_otp WHERE phone=%s", (new_phone,))
        conn.commit()

        return {"message": "Mobile number updated successfully"}

    finally:
        conn.close()

