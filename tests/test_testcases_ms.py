"""Unit Test Cases For RailSathi Microservices."""
"""Coverage == 77%."""

import sys, os
sys.path.append(os.path.abspath(os.path.dirname(__file__) + "/.."))

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status
from main import app, enrich_complaint_response_and_trigger_email
import json
from io import BytesIO

# Mock complaint template used across multiple tests
def mock_complaint(complain_id: int = 1, overrides: dict | None = None) -> dict:
    c = {
        "complain_id": 1,
        "pnr_number": "1234567890",
        "is_pnr_validated": "Yes",
        "name": "Jane Doe",
        "mobile_number": "9998887776",
        "complain_type": "Lost Ticket",
        "complain_description": "Lost my ticket",
        "complain_date": "2024-09-01",
        "complain_status": "pending",
        "train_id": 101,
        "train_number": "12345",
        "train_name": "Express",
        "coach": "A1",
        "berth_no": 10,
        "created_at": "2024-09-01T10:00:00",
        "created_by": "Jane Doe",
        "updated_at": "2024-09-01T10:00:00",
        "updated_by": "Jane Doe",
        "customer_care": "9123183988",
        "train_depot": "NDLS",
        "rail_sathi_complain_media_files": [],
    }
    if overrides:
        c.update(overrides)
    return c


# Mocked microservice functions.
def mock_get_complaint_by_id(complain_id: int):
    """Return None for id 999 to simulate not-found, otherwise base complaint."""
    if complain_id == 999:
        return None
    return mock_complaint(complain_id)

def mock_get_complaints_by_date(date: str, mobile: str):
    """Complaint Microservice - Fetch complaints by date and mobile number."""
    return [mock_complaint(1, {"mobile_number": mobile, "complain_date": date})]

def mock_create_complaint(data: dict):
    """Complaint Microservice - Create complaint."""
    return mock_complaint(1, {
        "name": data.get("name"),
        "mobile_number": data.get("mobile_number"),
        "complain_type": data.get("complain_type"),
        "complain_description": data.get("complain_description", "Lost my ticket"),
        "created_by": data.get("name"),
        "updated_by": data.get("name"),
        "is_pnr_validated": "not-attempted",
        "complain_status": "pending",
        "rail_sathi_complain_media_files": [
            {
                "id": 1,
                "filename": "dummy.txt",
                "media_type": "text/plain",
                "media_url": "/dummy.txt",
                "created_at": "2024-09-01T10:00:00",
                "updated_at": "2024-09-01T10:00:00",
                "created_by": data.get("name"),
                "updated_by": data.get("name"),
            }
        ],
    })

def mock_update_complaint(complain_id, update_data):
    """Complaint Microservice - Update complaint."""
    base = mock_get_complaint_by_id(complain_id) or {}
    return {**base, **update_data}

async def mock_enrich_complaint_response_and_trigger_email(**kwargs):
    """Complaint Microservice - Enrich complaint response and send email."""
    complaint = mock_get_complaint_by_id(kwargs.get("complain_id")) or {}
    for k, v in kwargs.items():
        if v is not None:
            complaint[k] = v
    complaint["submission_status"] = "submitted"
    complaint.setdefault("rail_sathi_complain_media_files", [])
    return complaint

def mock_upload_file_thread(file_obj, complain_id, name):
    """Complaint Microservice - Simulate file upload."""
    return True

def mock_delete_complaint_media(complain_id, ids):
    """Complaint Microservice - Delete media files from a complaint."""
    return len(ids)

def mock_delete_complaint(complain_id):
    """Complaint Microservice - Delete complaint by ID."""
    return True

# Full complaint template used in some tests
full_complaint_template = {
    "complain_id": 1,
    "pnr_number": "1234567890",
    "is_pnr_validated": "False",
    "name": "Jane Doe",
    "created_by": "Jane Doe",
    "mobile_number": "9998887776",
    "complain_type": "general",
    "complain_description": "Original description",
    "complain_date": "2025-09-01",
    "complain_status": "pending",
    "train_id": 101,
    "train_number": "12345",
    "train_name": "Express",
    "coach": "A1",
    "berth_no": 12,
    "rail_sathi_complain_media_files": [],
    "created_at": "2025-09-01T00:00:00",
    "updated_at": "2025-09-01T00:00:00",
    "updated_by": "Jane Doe",
    "customer_care": "info@example.com",
    "train_depot": "Depot 1"
}

async def make_request(method, url, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.request(method=method, url=url, **kwargs)


# Complaint Microservice - GET complaint by ID
@pytest.mark.asyncio
async def test_get_complaint_found(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    res = await make_request("GET", "/rs_microservice/complaint/get/1")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["message"] == "Complaint retrieved successfully"
    assert data["data"]["complain_id"] == 1
    assert data["data"]["complain_type"] == "Lost Ticket"


# Complaint Microservice - GET complaint not found
@pytest.mark.asyncio
async def test_get_complaint_not_found(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)
    res = await make_request("GET", "/rs_microservice/complaint/get/999")
    assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert res.json()["detail"] == "Internal server error"

# Complaint Microservice - GET complaint internal error
@pytest.mark.asyncio
async def test_get_complaint_internal_error(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: (_ for _ in ()).throw(Exception("DB connection lost!")))
    res = await make_request("GET", "/rs_microservice/complaint/get/123")
    assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert res.json()["detail"] == "Internal server error"

# Complaint Microservice - GET complaints by invalid date
@pytest.mark.asyncio
async def test_get_complaints_invalid_date():
    res = await make_request("GET", "/rs_microservice/complaint/get/date/2024-13-01", params={"mobile_number": "9876543210"})
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.json()["detail"] == "Invalid date format. Use YYYY-MM-DD."

@pytest.mark.asyncio
async def test_get_complaints_missing_mobile():
    res = await make_request("GET", "/rs_microservice/complaint/get/date/2024-09-01")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.json()["detail"] == "mobile_number parameter is required"

@pytest.mark.asyncio
async def test_get_complaints_empty_mobile():
    res = await make_request("GET", "/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": ""})
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.json()["detail"] == "mobile_number parameter is required"

@pytest.mark.asyncio
async def test_get_complaints_none(monkeypatch):
    monkeypatch.setattr("main.get_complaints_by_date", lambda d, m: [])
    res = await make_request("GET", "/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": "9876543210"})
    assert res.status_code == status.HTTP_200_OK
    assert res.json() == []

@pytest.mark.asyncio
async def test_get_complaints_success(monkeypatch):
    monkeypatch.setattr("main.get_complaints_by_date", mock_get_complaints_by_date)
    res = await make_request("GET", "/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": "9876543210"})
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data[0]["message"] == "Complaint retrieved successfully"
    assert data[0]["data"]["complain_id"] == 1

@pytest.mark.asyncio
async def test_get_complaints_internal_error(monkeypatch):
    monkeypatch.setattr("main.get_complaints_by_date", lambda d,m: (_ for _ in ()).throw(Exception("DB connection lost!")))
    res = await make_request("GET", "/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": "9876543210"})
    assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "Internal server error" in res.json()["detail"]

# Complaint Microservice - POST create complaint
@pytest.mark.asyncio
async def test_create_complaint_success(monkeypatch):
    monkeypatch.setattr("main.create_complaint", mock_create_complaint)
    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.send_plain_mail", lambda *a, **k: True)

    res = await make_request("POST", "/rs_microservice/complaint/add", data={
        "name": "John Doe", "mobile_number": "9998887776", "complain_type": "Lost Ticket"
    })
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["message"] == "Complaint created successfully"
    assert data["data"]["complain_id"] == 1
    assert data["data"]["name"] in ("Jane Doe", "John Doe")


# Complaint Microservice - PATCH update complaint
@pytest.mark.asyncio
async def test_update_complaint_success(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", mock_update_complaint)
    monkeypatch.setattr("main.enrich_complaint_response_and_trigger_email", mock_enrich_complaint_response_and_trigger_email)
    monkeypatch.setattr("main.upload_file_thread", mock_upload_file_thread)

    res = await make_request("PATCH", "/rs_microservice/complaint/update/1", data={
        "name": "Jane Doe", "mobile_number": "9998887776", "complain_type": "Lost Ticket"
    })
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["message"] == "Complaint updated successfully"
    updated_complaint = data.get("data", {})
    assert updated_complaint["name"] == "Jane Doe"
    assert updated_complaint["mobile_number"] == "9998887776"
    assert updated_complaint["complain_type"] == "Lost Ticket"

@pytest.mark.asyncio
async def test_update_complaint_not_found(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)
    res = await make_request("PATCH", "/rs_microservice/complaint/update/999", data={"name": "Jane Doe"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Complaint not found"

@pytest.mark.asyncio
async def test_update_complaint_with_files(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", mock_update_complaint)
    monkeypatch.setattr("main.enrich_complaint_response_and_trigger_email", mock_enrich_complaint_response_and_trigger_email)
    monkeypatch.setattr("main.upload_file_thread", mock_upload_file_thread)

    files = {"rail_sathi_complain_media_files": ("dummy.txt", b"dummy content", "text/plain")}
    res = await make_request("PATCH", "/rs_microservice/complaint/update/1", data={"name": "Jane Doe"}, files=files)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["message"] == "Complaint updated successfully"
    assert data["data"]["name"] == "Jane Doe"

@pytest.mark.asyncio
async def test_update_complaint_internal_error(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", lambda cid, d: (_ for _ in ()).throw(Exception("DB connection failed")))
    res = await make_request("PATCH", "/rs_microservice/complaint/update/1", data={"name": "Jane Doe", "complain_type": "Lost Ticket"})
    assert res.status_code == 500
    assert "Internal server error" in res.json()["detail"]


# Train Microservice - GET train details by train number
def mock_cursor_fetchone_train(train_no):
    if train_no == "12345":
        return {"train_no": "12345", "train_name": "Express", "Depot": "NDLS"}
    return None

def mock_cursor_fetchone_depot(depot_code):
    if depot_code == "NDLS":
        return {"depot_code": "NDLS", "division_id": 1}
    return None

def mock_cursor_fetchone_division(division_id):
    if division_id == 1:
        return {"division_id": 1, "division_code": "DEL", "zone_id": 10}
    return None

def mock_cursor_fetchone_zone(zone_id):
    if zone_id == 10:
        return {"zone_id": 10, "zone_code": "NR"}
    return None

class DummyCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))

    def fetchone(self):
        query, params = self.calls[-1]
        if "FROM trains_traindetails" in query:
            return mock_cursor_fetchone_train(params[0])
        if "FROM station_Depot" in query:
            return mock_cursor_fetchone_depot(params[0])
        if "FROM station_division" in query:
            return mock_cursor_fetchone_division(params[0])
        if "FROM station_zone" in query:
            return mock_cursor_fetchone_zone(params[0])
        return None

    def close(self):
        pass

class DummyConn:
    def cursor(self, cursor_factory=None):
        return DummyCursor()

    def close(self):
        pass

@pytest.mark.asyncio
async def test_train_found(monkeypatch):
    monkeypatch.setattr("main.get_db_connection", lambda: DummyConn())
    res = await make_request("GET", "/rs_microservice/train_details/12345")
    assert res.status_code == 200
    data = res.json()
    assert data["train_no"] == "12345"
    assert data["extra_info"]["depot_code"] == "NDLS"
    assert data["extra_info"]["division_code"] == "DEL"
    assert data["extra_info"]["zone_code"] == "NR"

@pytest.mark.asyncio
async def test_train_not_found(monkeypatch):
    monkeypatch.setattr("main.get_db_connection", lambda: DummyConn())
    res = await make_request("GET", "/rs_microservice/train_details/99999")
    assert res.status_code == 404
    assert res.json()["error"] == "Train not found"


# Health Check Microservice
@pytest.mark.asyncio
async def test_health_check():
    res = await make_request("GET", "/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}

@pytest.mark.asyncio
async def test_enrich_complaint_response_and_trigger_email(monkeypatch):
    monkeypatch.setattr("main.get_db_connection", lambda: type('C', (), {'close': lambda self: True})())
    def mock_execute_query(conn, query):
        if "trains_traindetails" in query:
            return [{"Depot": "NDLS"}]
        if "user_onboarding_user" in query:
            return [{"phone": "9998887776"}]
        return []
    monkeypatch.setattr("main.execute_query", mock_execute_query)
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: mock_complaint(complain_id=cid))
    monkeypatch.setattr("main.send_plain_mail", lambda **kwargs: True)
    result = await enrich_complaint_response_and_trigger_email(complain_id=1, pnr_number="1234567890", train_number="12345", coach="A1", berth_no=10, date_of_journey="2024-09-01")
    assert result["complain_id"] == 1
    assert result["train_depot"] == "NDLS"
    assert result["customer_care"] == "9998887776"
    assert result["name"] == "Jane Doe"


# Media Deletion - Complaint Microservice - DELETE media files
@pytest.mark.asyncio
async def test_delete_media_success(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: mock_complaint(cid))
    monkeypatch.setattr("main.delete_complaint_media", mock_delete_complaint_media)
    res = await make_request("DELETE", "/rs_microservice/media/delete/1", data={"name": "Jane Doe", "mobile_number": "9998887776", "deleted_media_ids": [101, 102]})
    assert res.status_code == 200
    assert res.json()["message"] == "2 media file(s) deleted successfully."

@pytest.mark.asyncio
async def test_delete_media_complaint_not_found(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)
    res = await make_request("DELETE", "/rs_microservice/media/delete/999", data={"name": "Jane Doe", "mobile_number": "9998887776", "deleted_media_ids": [101]})
    assert res.status_code == 404
    assert res.json()["detail"] == "Complaint not found"

@pytest.mark.asyncio
async def test_delete_media_permission_denied(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {**mock_complaint(cid), "created_by": "Another User"})
    res = await make_request("DELETE", "/rs_microservice/media/delete/1", data={"name": "Jane Doe", "mobile_number": "9998887776", "deleted_media_ids": [101]})
    assert res.status_code == 403
    assert "Only user who created the complaint" in res.json()["detail"]

@pytest.mark.asyncio
async def test_delete_media_internal_error(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: mock_complaint(cid))
    monkeypatch.setattr("main.delete_complaint_media", lambda cid, ids: (_ for _ in ()).throw(Exception("DB connection failed")))
    res = await make_request("DELETE", "/rs_microservice/media/delete/1", data={"name": "Jane Doe", "mobile_number": "9998887776", "deleted_media_ids": [101]})
    assert res.status_code == 500
    assert "Internal server error" in res.json()["detail"]

@pytest.mark.asyncio
async def test_delete_complaint_success(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: mock_complaint(cid))
    monkeypatch.setattr("main.delete_complaint", mock_delete_complaint)
    res = await make_request("DELETE", "/rs_microservice/complaint/delete/1", data={"name": "Jane Doe", "mobile_number": "9998887776"})
    assert res.status_code == 200
    assert res.json()["message"] == "Complaint deleted successfully"

@pytest.mark.asyncio
async def test_delete_complaint_not_found(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)
    res = await make_request("DELETE", "/rs_microservice/complaint/delete/999", data={"name": "Jane Doe", "mobile_number": "9998887776"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Complaint not found"

@pytest.mark.asyncio
async def test_delete_complaint_permission_denied(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {**mock_complaint(cid), "created_by": "Another User"})
    res = await make_request("DELETE", "/rs_microservice/complaint/delete/1", data={"name": "Jane Doe", "mobile_number": "9998887776"})
    assert res.status_code == 403
    assert "Only user who created the complaint" in res.json()["detail"]

@pytest.mark.asyncio
async def test_delete_complaint_internal_error(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: mock_complaint(cid))
    monkeypatch.setattr("main.delete_complaint", lambda cid: (_ for _ in ()).throw(Exception("DB connection failed")))
    res = await make_request("DELETE", "/rs_microservice/complaint/delete/1", data={"name": "Jane Doe", "mobile_number": "9998887776"})
    assert res.status_code == 500
    assert "Internal server error" in res.json()["detail"]


# Complaint Replacement - PUT complaint update
@pytest.mark.asyncio
async def test_replace_complaint_success(monkeypatch):
    updated = full_complaint_template.copy()
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: updated)
    def upd(cid, data):
        updated.update(data); return updated
    monkeypatch.setattr("main.update_complaint", upd)
    res = await make_request("PUT", "/rs_microservice/complaint/update/1", data={"name": "Jane Doe", "mobile_number": "9998887776", "complain_description": "Updated description"})
    assert res.status_code == 200
    assert res.json()["message"] == "Complaint replaced successfully"
    assert res.json()["data"]["complain_description"] == "Updated description"

@pytest.mark.asyncio
async def test_replace_complaint_with_files(monkeypatch):
    updated = full_complaint_template.copy()
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: updated)
    def upd(cid, data):
        updated.update(data); return updated
    monkeypatch.setattr("main.update_complaint", upd)
    monkeypatch.setattr("main.upload_file_thread", lambda f, cid, user: True)
    files = {"rail_sathi_complain_media_files": ("test.txt", b"file content", "text/plain"), "name": (None, "Jane Doe"), "mobile_number": (None, "9998887776")}
    res = await make_request("PUT", "/rs_microservice/complaint/update/1", files=files)
    assert res.status_code == 200
    assert res.json()["message"] == "Complaint replaced successfully"

@pytest.mark.asyncio
async def test_replace_complaint_not_found(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)
    res = await make_request("PUT", "/rs_microservice/complaint/update/999", data={"name": "Jane Doe", "mobile_number": "9998887776"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Complaint not found"

@pytest.mark.asyncio
async def test_replace_complaint_permission_denied(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {**mock_complaint(cid), "created_by": "Another User"})
    res = await make_request("PUT", "/rs_microservice/complaint/update/1", data={"name": "Jane Doe", "mobile_number": "9998887776"})
    assert res.status_code == 403
    assert "Only user who created the complaint" in res.json()["detail"]

@pytest.mark.asyncio
async def test_replace_complaint_internal_error(monkeypatch):
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: mock_complaint(cid))
    monkeypatch.setattr("main.update_complaint", lambda cid, data: (_ for _ in ()).throw(Exception("DB connection failed")))
    res = await make_request("PUT", "/rs_microservice/complaint/update/1", data={"name": "Jane Doe", "mobile_number": "9998887776"})
    assert res.status_code == 500
    assert "Internal server error" in res.json()["detail"]
