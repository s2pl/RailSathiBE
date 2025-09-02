import sys, os
sys.path.append(os.path.abspath(os.path.dirname(__file__) + "/.."))

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status, UploadFile
from main import app
from httpx import ASGITransport, AsyncClient
from httpx._transports.asgi import ASGITransport
from main import app, enrich_complaint_response_and_trigger_email
import json
from io import BytesIO

@pytest.mark.asyncio
async def test_get_complaint_found(monkeypatch):
    """Test: complaint exists (mock DB call)"""

    def mock_get_complaint_by_id(complain_id: int):
        return {
            "complain_id": complain_id,
            "pnr_number": "1234567890",
            "is_pnr_validated": "Yes",
            "name": "John Doe",
            "mobile_number": "9876543210",
            "complain_type": "Lost Ticket",
            "complain_description": "Lost my ticket during travel",
            "complain_date": "2024-09-01",
            "complain_status": "Open",
            "train_id": 101,
            "train_number": "12345",
            "train_name": "Rajdhani Express",
            "coach": "S1",
            "berth_no": "12",
            "created_at": "2024-09-01T12:00:00Z",
            "created_by": "system",
            "updated_at": "2024-09-01T12:00:00Z",
            "updated_by": "system",
            "customer_care": "Support",
            "train_depot": "NDLS",
            "rail_sathi_complain_media_files": [],
        }

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/1")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["message"] == "Complaint retrieved successfully"
    assert data["data"]["complain_id"] == 1
    assert data["data"]["complain_type"] == "Lost Ticket"


@pytest.mark.asyncio
async def test_get_complaint_not_found(monkeypatch):
    """Test: complaint does not exist (API currently returns 500, not 404)"""

    def mock_get_complaint_by_id(complain_id: int):
        return None

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/999")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Internal server error"

@pytest.mark.asyncio
async def test_get_complaint_internal_error(monkeypatch):
    """Test: DB throws exception (simulate crash)"""

    def mock_get_complaint_by_id(complain_id: int):
        raise Exception("DB connection lost!")

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/123")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Internal server error"

@pytest.mark.asyncio
async def test_get_complaints_invalid_date(monkeypatch):
    """Invalid date format should return 400"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/date/2024-13-01", params={"mobile_number": "9876543210"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "Invalid date format. Use YYYY-MM-DD."

@pytest.mark.asyncio
async def test_get_complaints_missing_mobile(monkeypatch):
    """Missing mobile_number should return 400"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/date/2024-09-01")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "mobile_number parameter is required"

@pytest.mark.asyncio
async def test_get_complaints_empty_mobile(monkeypatch):
    """Empty mobile_number should return 400"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": ""})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "mobile_number parameter is required" 

@pytest.mark.asyncio
async def test_get_complaints_none(monkeypatch):
    """No complaints found should return empty list"""
    def mock_get_complaints_by_date(date, mobile):
        return []

    monkeypatch.setattr("main.get_complaints_by_date", mock_get_complaints_by_date)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": "9876543210"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []

@pytest.mark.asyncio
async def test_get_complaints_success(monkeypatch):
    """Complaints returned successfully"""
    def mock_get_complaints_by_date(date, mobile):
        return [{
            "complain_id": 1,
            "pnr_number": "1234567890",
            "is_pnr_validated": "Yes",
            "name": "John Doe",
            "mobile_number": "9876543210",
            "complain_type": "Lost Ticket",
            "complain_description": "Lost ticket",
            "complain_date": "2024-09-01",
            "complain_status": "Open",
            "train_id": 101,
            "train_number": "12345",
            "train_name": "Rajdhani Express",
            "coach": "S1",
            "berth_no": "12",
            "created_at": "2024-09-01",
            "created_by": "system",
            "updated_at": "2024-09-01",
            "updated_by": "system",
            "customer_care": None,
            "train_depot": "NDLS",
            "rail_sathi_complain_media_files": [],
        }]

    monkeypatch.setattr("main.get_complaints_by_date", mock_get_complaints_by_date)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": "9876543210"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data[0]["message"] == "Complaint retrieved successfully"
    assert data[0]["data"]["complain_id"] == 1

@pytest.mark.asyncio
async def test_get_complaints_internal_error(monkeypatch):
    """Simulate internal server error"""
    def mock_get_complaints_by_date(date, mobile):
        raise Exception("DB connection lost!")

    monkeypatch.setattr("main.get_complaints_by_date", mock_get_complaints_by_date)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/complaint/get/date/2024-09-01", params={"mobile_number": "9876543210"})
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "Internal server error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_complaint_success(monkeypatch):
    """Test successful complaint creation with no files"""

    def mock_create_complaint(data):
        return {
        "complain_id": 1,
        "pnr_number": data.get("pnr_number", "1234567890"),
        "is_pnr_validated": "not-attempted",
        "name": data.get("name"),  # use input
        "mobile_number": data.get("mobile_number"),
        "complain_type": data.get("complain_type"),
        "complain_description": data.get("complain_description", "Lost my ticket"),
        "complain_date": "2024-09-01",
        "complain_status": "pending",
        "train_id": 101,
        "train_number": "12345",
        "train_name": "Express",
        "coach": "A1",
        "berth_no": 10,
        "created_at": "2024-09-01T10:00:00",
        "created_by": data.get("name"),
        "updated_at": "2024-09-01T10:00:00",
        "updated_by": data.get("name"),
        "rail_sathi_complain_media_files": [
            {
                "id": 1,
                "filename": "dummy.txt",
                "media_type": "text/plain",
                "media_url": "/dummy.txt",
                "created_at": "2024-09-01T10:00:00",
                "updated_at": "2024-09-01T10:00:00",
                "created_by": data.get("name"),
                "updated_by": data.get("name")
            }
        ],
        "train_depot": "NDLS",
        "customer_care": "9123183988"
    }

    def mock_get_complaint_by_id(complain_id):
        return {
        "complain_id": complain_id,
        "pnr_number": "1234567890",
        "is_pnr_validated": "not-attempted",
        "name": "Jane Doe",
        "mobile_number": "9876543210",
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
        "rail_sathi_complain_media_files": [
            {
                "id": 1,
                "filename": "dummy.txt",
                "media_type": "text/plain",
                "media_url": "/dummy.txt",
                "created_at": "2024-09-01T10:00:00",
                "updated_at": "2024-09-01T10:00:00",
                "created_by": "Jane Doe",
                "updated_by": "Jane Doe"
            }
        ],
        "train_depot": "NDLS",
        "customer_care": "9123183988"
    }

    def mock_send_plain_mail(subject, message, from_, to):
        return True

    monkeypatch.setattr("main.create_complaint", mock_create_complaint)
    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.send_plain_mail", mock_send_plain_mail)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/rs_microservice/complaint/add",
            data={
                "name": "John Doe",
                "mobile_number": "9876543210",
                "complain_type": "Lost Ticket"
            }
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["message"] == "Complaint created successfully"
    assert data["data"]["complain_id"] == 1
    assert data["data"]["name"] == "Jane Doe"

def mock_get_complaint_by_id(cid):
    return {
        "complain_id": cid,
        "pnr_number": "1234567890",
        "is_pnr_validated": "not-attempted",
        "name": "Jane Doe",
        "mobile_number": "9876543210",
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
        "rail_sathi_complain_media_files": [
            {
                "id": 1,
                "filename": "dummy.txt",
                "media_type": "text/plain",
                "media_url": "/dummy.txt",
                "created_at": "2024-09-01T10:00:00",
                "updated_at": "2024-09-01T10:00:00",
                "created_by": "Jane Doe",
                "updated_by": "Jane Doe"
            }
        ],
        "train_depot": "NDLS",
        "customer_care": "9123183988"
    }


def mock_get_complaint_by_id(cid):
    if cid == 999:
        return None
    return {
        "complain_id": cid,
        "pnr_number": "1234567890",
        "is_pnr_validated": "not-attempted",
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
        "rail_sathi_complain_media_files": [],
        "train_depot": "NDLS",
        "customer_care": "9123183988"
    }

def mock_update_complaint(complain_id, update_data):
    return {**mock_get_complaint_by_id(complain_id), **update_data}

async def mock_enrich_complaint_response_and_trigger_email(**kwargs):
    complaint = mock_get_complaint_by_id(kwargs.get("complain_id"))

    for k, v in kwargs.items():
        if v is not None:
            complaint[k] = v

    complaint["submission_status"] = "submitted"

    if "rail_sathi_complain_media_files" not in complaint:
        complaint["rail_sathi_complain_media_files"] = []

    return complaint

def mock_upload_file_thread(file_obj, complain_id, name):
    return True

@pytest.mark.asyncio
async def test_update_complaint_success(monkeypatch):
    """Test updating complaint successfully with partial fields"""

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", mock_update_complaint)
    monkeypatch.setattr("main.enrich_complaint_response_and_trigger_email", mock_enrich_complaint_response_and_trigger_email)
    monkeypatch.setattr("main.upload_file_thread", mock_upload_file_thread)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.patch(
            "/rs_microservice/complaint/update/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776",
                "complain_type": "Lost Ticket"
            }
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["message"] == "Complaint updated successfully"
    updated_complaint = data.get("data", {})
    assert updated_complaint["name"] == "Jane Doe"
    assert updated_complaint["mobile_number"] == "9998887776"
    assert updated_complaint["complain_type"] == "Lost Ticket"


@pytest.mark.asyncio
async def test_update_complaint_not_found(monkeypatch):
    """Test updating a complaint that does not exist"""

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.patch(
            "/rs_microservice/complaint/update/999",
            data={"name": "Jane Doe"}
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Complaint not found"

@pytest.mark.asyncio
async def test_update_complaint_with_files(monkeypatch):
    """Test updating complaint with file uploads"""

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", mock_update_complaint)
    monkeypatch.setattr("main.enrich_complaint_response_and_trigger_email", mock_enrich_complaint_response_and_trigger_email)
    monkeypatch.setattr("main.upload_file_thread", mock_upload_file_thread)

    class DummyUploadFile:
        filename = "dummy.txt"
        content_type = "text/plain"
        async def read(self):
            return b"dummy content"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.patch(
            "/rs_microservice/complaint/update/1",
            data={"name": "Jane Doe"},
            files={"rail_sathi_complain_media_files": ("dummy.txt", b"dummy content", "text/plain")}
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["message"] == "Complaint updated successfully"
    assert data["data"]["name"] == "Jane Doe"

@pytest.mark.asyncio
async def test_update_complaint_internal_error(monkeypatch):
    """Test server error during update"""
    complain_id = 1

    def mock_update_error(complain_id, update_data):
        raise Exception("DB connection failed")

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", mock_update_error)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.patch(
        f"/rs_microservice/complaint/update/{complain_id}",
        data={
            "name": "Jane Doe",
            "complain_type": "Lost Ticket"
        }
    )

    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


def mock_cursor_fetchone_train(train_no):
    if train_no == "12345":
        return {
            "train_no": "12345",
            "train_name": "Express",
            "Depot": "NDLS",
        }
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
        # Return appropriate mock based on last executed query
        if "FROM trains_traindetails" in self.calls[-1][0]:
            return mock_cursor_fetchone_train(self.calls[-1][1][0])
        elif "FROM station_Depot" in self.calls[-1][0]:
            return mock_cursor_fetchone_depot(self.calls[-1][1][0])
        elif "FROM station_division" in self.calls[-1][0]:
            return mock_cursor_fetchone_division(self.calls[-1][1][0])
        elif "FROM station_zone" in self.calls[-1][0]:
            return mock_cursor_fetchone_zone(self.calls[-1][1][0])
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
    
    transport = ASGITransport(app=app)  # wrap your FastAPI app
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/train_details/12345")

    assert response.status_code == 200
    data = response.json()
    assert data["train_no"] == "12345"
    assert data["extra_info"]["depot_code"] == "NDLS"
    assert data["extra_info"]["division_code"] == "DEL"
    assert data["extra_info"]["zone_code"] == "NR"

@pytest.mark.asyncio
async def test_train_not_found(monkeypatch):
    monkeypatch.setattr("main.get_db_connection", lambda: DummyConn())
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/rs_microservice/train_details/99999")

    assert response.status_code == 404
    assert response.json()["error"] == "Train not found"


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


class DummyConnSimple:
    def close(self):
        return True  

@pytest.mark.asyncio
async def test_enrich_complaint_response_and_trigger_email(monkeypatch):
    """Test the enrichment function without DB or email calls"""

    monkeypatch.setattr("main.get_db_connection", lambda: DummyConnSimple())

    def mock_execute_query(conn, query):
        if "SELECT \"Depot\" FROM trains_traindetails" in query:
            return [{"Depot": "NDLS"}]
        if "FROM user_onboarding_user" in query:
            return [{"phone": "9998887776"}]
        return []

    monkeypatch.setattr("main.execute_query", mock_execute_query)

    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "name": "Jane Doe",
        "pnr_number": "1234567890",
        "train_number": "12345",
        "coach": "A1",
        "berth_no": 10
    })

    monkeypatch.setattr("main.send_plain_mail", lambda **kwargs: True)

    result = await enrich_complaint_response_and_trigger_email(
        complain_id=1,
        pnr_number="1234567890",
        train_number="12345",
        coach="A1",
        berth_no=10,
        date_of_journey="2024-09-01"
    )

    assert result["complain_id"] == 1
    assert result["train_depot"] == "NDLS"
    assert result["customer_care"] == "9998887776"
    assert result["name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_delete_media_success(monkeypatch):
    """Test successful deletion of media files"""

    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "name": "Jane Doe",
        "created_by": "Jane Doe",
        "mobile_number": "9998887776",
        "complain_status": "pending",
    })
    monkeypatch.setattr("main.delete_complaint_media", lambda cid, ids: len(ids))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/media/delete/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776",
                "deleted_media_ids": [101, 102]
            }
        )

    assert response.status_code == 200
    assert response.json()["message"] == "2 media file(s) deleted successfully."


@pytest.mark.asyncio
async def test_delete_media_complaint_not_found(monkeypatch):
    """Test deletion with invalid complaint ID"""

    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/media/delete/999",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776",
                "deleted_media_ids": [101]
            }
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Complaint not found"


@pytest.mark.asyncio
async def test_delete_media_permission_denied(monkeypatch):
    """Test deletion when user info does not match or complaint completed"""

    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "created_by": "Another User",
        "mobile_number": "9998887776",
        "complain_status": "pending"
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/media/delete/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776",
                "deleted_media_ids": [101]
            }
        )

    assert response.status_code == 403
    assert "Only user who created the complaint" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_media_internal_error(monkeypatch):
    """Test server error during deletion"""

    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "created_by": "Jane Doe",
        "mobile_number": "9998887776",
        "complain_status": "pending"
    })

    def mock_delete(cid, ids):
        raise Exception("DB connection failed")

    monkeypatch.setattr("main.delete_complaint_media", mock_delete)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/media/delete/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776",
                "deleted_media_ids": [101]
            }
        )

    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]

@pytest.mark.asyncio
async def test_delete_complaint_success(monkeypatch):
    """Test successful deletion of a complaint"""
    
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "created_by": "Jane Doe",
        "mobile_number": "9998887776",
        "complain_status": "pending",
    })
    monkeypatch.setattr("main.delete_complaint", lambda cid: True)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/complaint/delete/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776"
            }
        )
    
    assert response.status_code == 200
    assert response.json()["message"] == "Complaint deleted successfully"


@pytest.mark.asyncio
async def test_delete_complaint_not_found(monkeypatch):
    """Test deletion when complaint does not exist"""
    
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/complaint/delete/999",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776"
            }
        )
    
    assert response.status_code == 404
    assert response.json()["detail"] == "Complaint not found"

@pytest.mark.asyncio
async def test_delete_complaint_permission_denied(monkeypatch):
    """Test deletion when user info does not match or complaint completed"""
    
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "created_by": "Another User",
        "mobile_number": "9998887776",
        "complain_status": "pending"
    })
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/complaint/delete/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776"
            }
        )
    
    assert response.status_code == 403
    assert "Only user who created the complaint" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_complaint_internal_error(monkeypatch):
    """Test server error during deletion"""
    
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "created_by": "Jane Doe",
        "mobile_number": "9998887776",
        "complain_status": "pending"
    })
    
    def mock_delete(cid):
        raise Exception("DB connection failed")
    
    monkeypatch.setattr("main.delete_complaint", mock_delete)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.request(
            method="DELETE",
            url="/rs_microservice/complaint/delete/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776"
            }
        )
    
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]

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

@pytest.mark.asyncio
async def test_replace_complaint_success(monkeypatch):
    """Test successful replacement without files"""

    updated_complaint = full_complaint_template.copy()

    def mock_get_complaint_by_id(cid):
        return updated_complaint

    def mock_update_complaint(cid, data):
        updated_complaint.update(data)
        return updated_complaint

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", mock_update_complaint)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.put(
            "/rs_microservice/complaint/update/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776",
                "complain_description": "Updated description"
            }
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Complaint replaced successfully"
    assert response.json()["data"]["complain_description"] == "Updated description"


@pytest.mark.asyncio
async def test_replace_complaint_with_files(monkeypatch):
    """Test successful replacement with file uploads"""

    updated_complaint = full_complaint_template.copy()

    def mock_get_complaint_by_id(cid):
        return updated_complaint

    def mock_update_complaint(cid, data):
        updated_complaint.update(data)
        return updated_complaint

    monkeypatch.setattr("main.get_complaint_by_id", mock_get_complaint_by_id)
    monkeypatch.setattr("main.update_complaint", mock_update_complaint)
    monkeypatch.setattr("main.upload_file_thread", lambda file_obj, cid, user: True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {
            "rail_sathi_complain_media_files": ("test.txt", b"file content", "text/plain"),
            "name": (None, "Jane Doe"),
            "mobile_number": (None, "9998887776")
        }
        response = await ac.put(
            "/rs_microservice/complaint/update/1",
            files=files
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Complaint replaced successfully"


@pytest.mark.asyncio
async def test_replace_complaint_not_found(monkeypatch):
    """Test update when complaint does not exist"""
    
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: None)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.put(
            "/rs_microservice/complaint/update/999",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776"
            }
        )
    
    assert response.status_code == 404
    assert response.json()["detail"] == "Complaint not found"


@pytest.mark.asyncio
async def test_replace_complaint_permission_denied(monkeypatch):
    """Test update when user info does not match or complaint completed"""
    
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "created_by": "Another User",
        "mobile_number": "9998887776",
        "complain_status": "pending"
    })
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.put(
            "/rs_microservice/complaint/update/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776"
            }
        )
    
    assert response.status_code == 403
    assert "Only user who created the complaint" in response.json()["detail"]


@pytest.mark.asyncio
async def test_replace_complaint_internal_error(monkeypatch):
    """Test server error during update"""
    
    monkeypatch.setattr("main.get_complaint_by_id", lambda cid: {
        "complain_id": cid,
        "created_by": "Jane Doe",
        "mobile_number": "9998887776",
        "complain_status": "pending"
    })
    
    def mock_update(cid, data):
        raise Exception("DB connection failed")
    
    monkeypatch.setattr("main.update_complaint", mock_update)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.put(
            "/rs_microservice/complaint/update/1",
            data={
                "name": "Jane Doe",
                "mobile_number": "9998887776"
            }
        )
    
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]