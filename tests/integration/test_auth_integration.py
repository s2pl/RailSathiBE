import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from database import get_db_connection, execute_query
from passlib.hash import django_pbkdf2_sha256
from datetime import datetime
import io
from unittest.mock import patch
import pytest_asyncio
import uuid
from services import upload_file_thread, send_plain_mail, create_complaint
import auth_api_services

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# ---------------- Fixtures ---------------- #




@pytest.mark.asyncio
async def test_roles_table_exists(db_conn):
    rows = execute_query(db_conn, "SELECT table_name FROM information_schema.tables WHERE table_name='user_onboarding_roles';")
    assert len(rows) == 1

@pytest.mark.asyncio
async def test_insert_and_fetch_role(db_conn):
    execute_query(
        db_conn,
        "INSERT INTO user_onboarding_roles (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (9999, "pytest_role"),
)
    db_conn.commit()


    rows = execute_query(db_conn, "SELECT name FROM user_onboarding_roles WHERE id=%s", (9999,))
    assert rows[0][0] == "pytest_role"

    execute_query(db_conn, "DELETE FROM user_onboarding_roles WHERE id=%s", (9999,))
    db_conn.commit()



@pytest.mark.asyncio
async def test_create_complaint(client, auth_token, db_conn):
    data = {
        "name": "John Doe",
        "mobile_number": "9999999999",
        "complain_type": "delay",
        "complain_description": "Train late by 2 hours",
        "complain_date": "2025-09-03",
        "train_number": "12345",
    }

    resp = await client.post(
        "/rs_microservice/v2/complaint/add",
        data=data,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["message"] == "Complaint created successfully"

# database.py
import logging
import psycopg2

def execute_query(conn, query, params=None):
    try:
        with conn.cursor() as cursor:   # ⚠️ don't force DictCursor
            cursor.execute(query, params)

            q = query.strip().lower()
            if q.startswith("select") or "returning" in q:
                rows = cursor.fetchall()
                # normalize: convert dict rows to tuples
                if rows and isinstance(rows[0], dict):
                    return [tuple(row.values()) for row in rows]
                return rows
            else:
                conn.commit()
                return []
    except psycopg2.ProgrammingError as e:
        logging.error(f"Query execution failed: {e}")
        logging.error(f"Query: {query}")
        logging.error(f"Params: {params}")
        conn.rollback()
        raise



@pytest.fixture
def setup_test_user(db_conn):
    password_hash = django_pbkdf2_sha256.hash("testpass")
    role = execute_query(
        db_conn,
        "INSERT INTO user_onboarding_roles (name) VALUES (%s) RETURNING id",
        ("TestRole",),
)
    if not role:
        pytest.fail("Failed to insert role into user_onboarding_roles")

    role_id = role[0][0]


    suffix = uuid.uuid4().hex[:6]
    username = f"testuser_{suffix}"
    email = f"test_{suffix}@example.com"
    phone = f"9{suffix:0<9}"[:10]

    execute_query(
        db_conn,
        """
        INSERT INTO user_onboarding_user (
            first_name, last_name, username, email, phone,
            password, created_at, created_by, updated_at, updated_by,
            is_active, staff, railway_admin, enabled, user_type_id, user_status
        )
        VALUES (
            'Test', 'User', %s, %s, %s,
            %s, NOW(), 'pytest', NOW(), 'pytest',
            true, false, false, true, %s, 'active'
        )
        RETURNING id
        """,
        (username, email, phone, password_hash, role_id),
    )
    db_conn.commit()

    yield username, "testpass"

    db_conn.rollback()
    execute_query(db_conn, "DELETE FROM user_onboarding_user WHERE username=%s", (username,))
    execute_query(db_conn, "DELETE FROM user_onboarding_roles WHERE id=%s", (role_id,))
    db_conn.commit()



@pytest_asyncio.fixture
async def auth_token(client, setup_test_user):
    username, password = setup_test_user
    resp = await client.post(
        "/rs_microservice/v2/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]




# ---------------- Tests ---------------- #

@pytest.mark.asyncio
async def test_create_complaint_dbverify(client, auth_token, db_conn):
    data = {
        "name": "John Doe",
        "mobile_number": "9999999999",
        "complain_type": "delay",
        "complain_description": "Train late by 2 hours",
        "complain_date": datetime.now().strftime("%Y-%m-%d"),
        "train_number": "12345"
    }

    resp = await client.post(
        "/rs_microservice/v2/complaint/add",
        data=data,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["message"] == "Complaint created successfully"
    complaint_id = payload["data"]["complain_id"]

    # Verify complaint exists in DB
    rows = execute_query(db_conn, "SELECT * FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,))
    assert len(rows) == 1

    # Cleanup
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,))
    db_conn.commit()


@pytest.mark.asyncio
async def test_get_complaint_insert(client, auth_token, db_conn):
    # Insert test complaint
    complaint_id = uuid.uuid4().int & (1<<31)-1
    execute_query(
        db_conn,
        """INSERT INTO rail_sathi_railsathicomplain
            (complain_id, name, mobile_number, complain_type, complain_status, complain_description, created_by, updated_by, created_at, updated_at)
        VALUES
            (5000, 'John Doe', '9999999999', 'delay', 'pending' , 'Testing fetch', 999, 999, NOW(), NOW())
        ON CONFLICT (complain_id) DO NOTHING""", (complaint_id,)
    )
    db_conn.commit()

    resp = await client.get(
        "/rs_microservice/v2/complaint/get/5000",
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"]["complain_id"] == 5000

    # Cleanup
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=5000", ())
    db_conn.commit()

import jwt
@pytest.mark.asyncio
async def test_delete_complaint(client, auth_token, db_conn):

    payload = jwt.decode(auth_token, options={"verify_signature": False})
    test_user_sub = payload["sub"]


    # Insert with created_by = that sub
    execute_query(
        db_conn,
        """INSERT INTO rail_sathi_railsathicomplain
            (complain_id, name, mobile_number, complain_type, complain_status, complain_description, created_by, updated_by, created_at, updated_at)
        VALUES
            (5000, 'John Doe', '9999999999', 'delay', 'pending', 'Testing fetch', %s, %s, NOW(), NOW())
        ON CONFLICT (complain_id) DO NOTHING""",
        (test_user_sub, test_user_sub)
)
    db_conn.commit()

    resp = await client.request("DELETE",
        "/rs_microservice/v2/complaint/delete/5000",
        data={"name": "John Doe", "mobile_number": "9999999999"},
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 200
    assert resp.json()["message"] == "Complaint deleted successfully"

    # Verify deletion
    rows = execute_query(db_conn, "SELECT * FROM rail_sathi_railsathicomplain WHERE complain_id=5000", ())
    assert len(rows) == 0


# -------------------- Happy Path: Complaint Creation --------------------
@pytest.mark.asyncio
async def test_create_complaint_success(client, auth_token, db_conn):
    data = {
        "name": "John Doe",
        "mobile_number": "9999999999",
        "complain_type": "delay",
        "complain_description": "Train late by 2 hours",
        "complain_date": datetime.now().strftime("%Y-%m-%d"),
        "train_number": "12345",
    }

    resp = await client.post(
        "/rs_microservice/v2/complaint/add",
        data=data,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["message"] == "Complaint created successfully"

    complaint_id = payload["data"]["complain_id"]
    print("API response payload:", payload)

    # verify row exists in real DB
    rows = execute_query(db_conn, "SELECT * FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,),)
    assert len(rows) == 1

    # cleanup
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,),)
    print("DB rows:", rows)

    db_conn.commit()


# -------------------- Invalid Auth --------------------
@pytest.mark.asyncio
async def test_create_complaint_unauthorized(client):
    """Should reject request if no auth token is provided."""
    data = {"name": "John Doe"}
    resp = await client.post("/rs_microservice/v2/complaint/add", data=data)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


# -------------------- File Upload --------------------
@pytest.mark.asyncio
async def test_create_complaint_with_file(client, auth_token, db_conn, setup_test_user):
    """Test complaint creation with file upload (mocked upload)."""
    file_content = io.BytesIO(b"fake image data")

    data = {
        "name": "Jane Doe",
        "mobile_number": "8888888888",
        "complain_type": "cleanliness",
        "complain_description": "Dirty coach",
        "complain_date": datetime.now().strftime("%Y-%m-%d"),
        "train_number": "54321",
    }

    files = {
        "rail_sathi_complain_media_files": ("test.jpg", file_content, "image/jpeg")
    }

    with patch("services.upload_file_thread", return_value=None):
        resp = await client.post(
            "/rs_microservice/v2/complaint/add",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["message"] == "Complaint created successfully"
    assert payload["data"]["complain_type"] == "cleanliness"

    complaint_id = payload["data"]["complain_id"]
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,))
    db_conn.commit()


# -------------------- Depot Not Found (default war room phone) --------------------
@pytest.mark.asyncio
async def test_create_complaint_no_depot(client, auth_token, db_conn, setup_test_user):
    """If no depot found, war room phone should fallback to default."""
    data = {
        "name": "John Depot",
        "mobile_number": "7777777777",
        "complain_type": "other",
        "complain_description": "Depot missing",
        "complain_date": datetime.now().strftime("%Y-%m-%d"),
        "train_number": "00000",  # assume not in DB
    }

    with patch("services.send_plain_mail", return_value=True):
        resp = await client.post(
            "/rs_microservice/v2/complaint/add",
            data=data,
            headers={"Authorization": f"Bearer {auth_token}"}
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"]["customer_care"] == "9123183988"

    complaint_id = payload["data"]["complain_id"]
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,))
    db_conn.commit()


# -------------------- Internal Server Error Mock --------------------
@pytest.mark.asyncio
async def test_create_complaint_internal_error(client, auth_token, setup_test_user):
    """Force error inside endpoint and verify 500 response."""
    data = {
        "name": "Broken User",
        "mobile_number": "1231231234",
        "complain_type": "test",
        "complain_description": "Force failure",
        "complain_date": datetime.now().strftime("%Y-%m-%d"),
    }

    with patch("auth_api_services.create_complaint", side_effect=Exception("DB error")):
        resp = await client.post(
            "/rs_microservice/v2/complaint/add",
            data=data,
            headers={"Authorization": f"Bearer {auth_token}"}
        )

    assert resp.status_code == 500
    assert "Internal server error" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_complaint_missing_field(client, auth_token):
    """Verify behavior when 'name' field is missing (optional in current API)."""
    data = {
        "mobile_number": "9999999999",
        # missing 'name'
        "complain_type": "delay",
        "complain_description": "Missing field test",
        "complain_date": datetime.now().strftime("%Y-%m-%d"),
        "train_number": "12345",
    }

    resp = await client.post(
        "/rs_microservice/v2/complaint/add",
        data=data,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    # The endpoint accepts missing 'name', so status code is 200
    assert resp.status_code == 200  

    resp_json = resp.json()
    # Verify 'name' is None
    assert resp_json["data"]["name"] is None
    # Verify other fields are correct
    assert resp_json["data"]["mobile_number"] == "9999999999"
    assert resp_json["data"]["complain_type"] == "delay"


@pytest.mark.asyncio
async def test_create_complaint_invalid_date(client, auth_token):
    """Test invalid date format, without changing endpoint code."""
    data = {
        "name": "John Doe",
        "mobile_number": "9999999999",
        "complain_type": "delay",
        "complain_description": "Invalid date test",
        "complain_date": "03-09-2025",  # wrong format
        "train_number": "12345",
    }

    resp = await client.post(
        "/rs_microservice/v2/complaint/add",
        data=data,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    # Endpoint returns 200, so check the date format manually
    response_data = resp.json().get("data", {})
    complain_date_str = response_data.get("complain_date", "")

    # Try to parse it in expected format
    try:
        datetime.strptime(complain_date_str, "%Y-%m-%d")
    except ValueError:
        pytest.fail(f"Complaint created with invalid date format: {complain_date_str}")

    # Optional: still assert 200 OK, because endpoint doesn’t reject
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_get_complaint_not_found(client, auth_token):
    """Should return 404 if complaint does not exist."""
    resp = await client.get(
        "/rs_microservice/v2/complaint/get/999999",  # assume not in DB
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 404
    assert "not found" in resp.text.lower()

@pytest.mark.asyncio
async def test_delete_complaint_not_found(client, auth_token):
    """Deleting a complaint that doesn't exist should return 404."""
    resp = await client.request("DELETE",
        "/rs_microservice/v2/complaint/delete/999999",
        data={"name": "Nobody", "mobile_number": "1111111111"},
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 404
    assert "not found" in resp.text.lower()

@pytest.mark.asyncio
async def test_create_complaint_large_file(client, auth_token):
    """Test complaint creation with oversized file."""
    big_content = io.BytesIO(b"x" * 5 * 1024 * 1024)  # 5MB

    data = {
        "name": "Big File User",
        "mobile_number": "7777777777",
        "complain_type": "other",
        "complain_description": "Large file upload",
        "complain_date": datetime.now().strftime("%Y-%m-%d"),
        "train_number": "11111",
    }

    files = {
        "rail_sathi_complain_media_files": ("bigfile.jpg", big_content, "image/jpeg")
    }

    resp = await client.post(
        "/rs_microservice/v2/complaint/add",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    # Either should succeed or return 413 Payload Too Large depending on config
    assert resp.status_code in (200, 413)

@pytest.mark.asyncio
async def test_create_complaint_invalid_token(client):
    """Should reject request with invalid/expired token."""
    data = {"name": "Bad Token User", "mobile_number": "0000000000"}

    resp = await client.post(
        "/rs_microservice/v2/complaint/add",
        data=data,
        headers={"Authorization": "Bearer invalidtoken123"}
    )

    assert resp.status_code == 401
    assert "Invalid or expired token" in resp.text


# conftest.py
import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def disable_email(monkeypatch):
    """Prevent real emails from being sent during tests."""
    def fake_send_email(*args, **kwargs):
        return True
    def fake_send_mail(*args, **kwargs):
        return True

    monkeypatch.setattr("utils.email_utils.send_plain_mail", fake_send_email)

#-----------------Update------------------

# ------------------ Happy Path: Partial Update ------------------ #
@pytest.mark.asyncio
async def test_update_complaint_partial(client, auth_token, db_conn):
    """Update only a few fields of an existing complaint."""
    # Insert a complaint
    complaint_id = 7000
    execute_query(db_conn,
        """INSERT INTO rail_sathi_railsathicomplain
        (complain_id, name, mobile_number, complain_type, complain_status, complain_description, created_by, updated_by, created_at, updated_at)
        VALUES (%s, 'John Doe', '9999999999', 'delay', 'pending', 'Initial description', 1, 1, NOW(), NOW())
        ON CONFLICT (complain_id) DO NOTHING""",
        (complaint_id,)
    )
    db_conn.commit()

    data = {
        "complain_description": "Updated description",
        "complain_status": "in_progress"
    }

    resp = await client.patch(
        f"/rs_microservice/v2/complaint/update/{complaint_id}",
        data=data,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["message"] == "Complaint updated successfully"
    assert payload["data"]["complain_description"] == "Updated description"
    assert payload["data"]["complain_status"] == "in_progress"

    # Cleanup
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,))
    db_conn.commit()


# ------------------ Update Nonexistent Complaint ------------------ #
@pytest.mark.asyncio
async def test_update_complaint_not_found(client, auth_token):
    """Updating a non-existent complaint should return 404."""
    resp = await client.patch(
        "/rs_microservice/v2/complaint/update/999999",
        data={"complain_description": "Does not exist"},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


# ------------------ Update with File Upload ------------------ #
@pytest.mark.asyncio
async def test_update_complaint_with_file(client, auth_token, db_conn):
    """Update complaint with a file upload (mocked)."""
    # Insert a complaint
    complaint_id = 7001
    execute_query(db_conn,
        """INSERT INTO rail_sathi_railsathicomplain
        (complain_id, name, mobile_number, complain_type, complain_status, complain_description, created_by, updated_by, created_at, updated_at)
        VALUES (%s, 'Jane Doe', '8888888888', 'cleanliness', 'pending', 'Initial desc', 1, 1, NOW(), NOW())
        ON CONFLICT (complain_id) DO NOTHING""",
        (complaint_id,)
    )
    db_conn.commit()

    file_content = io.BytesIO(b"fake image data")
    files = {"rail_sathi_complain_media_files": ("test.jpg", file_content, "image/jpeg")}
    data = {"complain_description": "Updated with file"}

    with patch("services.upload_file_thread", return_value=None):
        resp = await client.patch(
            f"/rs_microservice/v2/complaint/update/{complaint_id}",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"]["complain_description"] == "Updated with file"

    # Cleanup
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,))
    db_conn.commit()


# ------------------ Update All Fields ------------------ #
@pytest.mark.asyncio
async def test_update_complaint_all_fields(client, auth_token, db_conn):
    """Update all optional fields."""

    complaint_id = 7002

    # Insert dummy complaint
    execute_query(db_conn,
        """INSERT INTO rail_sathi_railsathicomplain
        (complain_id, name, mobile_number, complain_type, complain_status, complain_description, created_by, updated_by, created_at, updated_at)
        VALUES (%s, 'Full Update', '7777777777', 'delay', 'pending', 'Initial desc', 1, 1, NOW(), NOW())
        ON CONFLICT (complain_id) DO NOTHING""",
        (complaint_id,)
    )

    execute_query(db_conn,
    """INSERT INTO trains_traindetails 
       (id, train_no, "Depot", train_name, train_type, frequency, from_station, to_station,
        stopages_in_sequence, coaches_in_sequence, arrival_time, is_location_restriction,
        is_time_resriction, media_upload_enabled)
       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
       ON CONFLICT (id) DO NOTHING""",
    (
        123,                   # id
        45678,                 # train_no
        "DefaultDepot",        # Depot
        "Express",             # train_name
        "Mail",                # train_type
        "{}",                  # frequency (jsonb)
        "StationA",            # from_station
        "StationB",            # to_station
        "[]",                  # stopages_in_sequence (jsonb)
        "[]",                  # coaches_in_sequence (jsonb)
        "[]",                  # arrival_time (jsonb)
        False,                 # is_location_restriction
        False,                 # is_time_resriction
        False                  # media_upload_enabled
    )
)

    db_conn.commit()

    data = {
        "pnr_number": "PNR12345",
        "is_pnr_validated": "yes",
        "name": "Updated Name",
        "mobile_number": "9999999999",
        "complain_type": "other",
        "complain_description": "Full update description",
        "complain_date": "2025-09-09",
        "complain_status": "completed",
        "id": 123,
        "train_number": "45678",
        "train_name": "Express",
        "coach": "A1",
        "berth_no": 12
    }

    resp = await client.patch(
        f"/rs_microservice/v2/complaint/update/{complaint_id}",
        data=data,
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"]["pnr_number"] == "PNR12345"
    assert payload["data"]["complain_status"] == "completed"

    # Cleanup complaint and dummy train
    execute_query(db_conn, "DELETE FROM rail_sathi_railsathicomplain WHERE complain_id=%s", (complaint_id,))
    execute_query(db_conn, "DELETE FROM trains_traindetails WHERE id=%s", (123,))
    db_conn.commit()

