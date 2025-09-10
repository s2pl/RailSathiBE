from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
import pytest
from unittest.mock import patch, MagicMock
import io
from datetime import timedelta
from jose import jwt
import auth_api_services
from auth_api_services import router, create_access_token

# -------------------- FastAPI Test App Setup --------------------
test_app = FastAPI()
test_app.include_router(router)
client = TestClient(test_app)

# -------------------- Reusable Data --------------------
VALID_COMPLAINT = {
    "complain_id": 1,
    "pnr_number": "1234567890",
    "is_pnr_validated": "not-attempted",
    "name": "Test User",
    "mobile_number": "9876543210",
    "complain_type": "cleaning",
    "complain_description": "Seat not clean",
    "complain_status": "pending",
    "complain_date": "2025-08-22",
    "train_number": "12256",
    "train_name": "Express",
    "coach": "S2",
    "berth_no": 10,
    "created_at": "2025-08-22",
    "created_by": "tester",
    "updated_at": "2025-08-22",
    "updated_by": "tester",
}

# -------------------- Fixtures --------------------
@pytest.fixture
def valid_token():
    return create_access_token({"sub": "testuser"})

@pytest.fixture
def expired_token():
    return create_access_token({"sub": "testuser"}, expires_delta=timedelta(seconds=-1))

# -------------------- JWT Tests --------------------
def test_create_access_token_and_decode():
    token = auth_api_services.create_access_token({"sub": "testuser"}, expires_delta=timedelta(minutes=5))
    decoded = jwt.decode(token, auth_api_services.SECRET_KEY, algorithms=[auth_api_services.ALGORITHM])
    assert decoded["sub"] == "testuser"

def test_get_current_user_valid_token(valid_token):
    result = auth_api_services.get_current_user(valid_token)
    assert result["username"] == "testuser"

def test_get_current_user_invalid_token():
    with pytest.raises(HTTPException):
        auth_api_services.get_current_user("badtoken")

def test_get_current_user_expired_token(expired_token):
    with pytest.raises(HTTPException):
        auth_api_services.get_current_user(expired_token)

# -------------------- Login Tests --------------------
@patch("auth_api_services.get_db_connection")
@patch("auth_api_services.execute_query")
def test_login_success(mock_exec, mock_conn):
    mock_conn.return_value = MagicMock()
    mock_exec.return_value = [
        {"username": "john", "password": auth_api_services.django_pbkdf2_sha256.hash("secret")}
    ]
    response = client.post("/rs_microservice/v2/token", data={"username": "john", "password": "secret"})
    assert response.status_code == 200
    assert "access_token" in response.json()

@pytest.mark.parametrize("mock_result,username,password", [
    ([], "nosuch", "bad"),
    ([{"username": "john", "password": auth_api_services.django_pbkdf2_sha256.hash("other")}], "john", "wrong")
])
@patch("auth_api_services.get_db_connection")
@patch("auth_api_services.execute_query")
def test_login_failures(mock_exec, mock_conn, mock_result, username, password):
    mock_conn.return_value = MagicMock()
    mock_exec.return_value = mock_result
    response = client.post("/rs_microservice/v2/token", data={"username": username, "password": password})
    assert response.status_code == 401

# -------------------- Complaint Retrieval --------------------
@patch("auth_api_services.get_complaint_by_id")
def test_get_complaint_found(mock_get, valid_token):
    mock_get.return_value = VALID_COMPLAINT
    response = client.get("/rs_microservice/v2/complaint/get/1",
                          headers={"Authorization": f"Bearer {valid_token}"})
    assert response.status_code == 200
    assert response.json()["data"]["complain_id"] == 1

@patch("auth_api_services.get_complaint_by_id")
def test_get_complaint_not_found(mock_get, valid_token):
    mock_get.return_value = None
    
    response = client.get("/rs_microservice/v2/complaint/get/99",
                          headers={"Authorization": f"Bearer {valid_token}"})
    assert response.status_code == 404

def test_invalid_token():
    response = client.get("/rs_microservice/v2/complaint/get/1",
                          headers={"Authorization": "Bearer invalidtoken"})
    assert response.status_code == 401

def test_token_and_get_complaint(monkeypatch):
    def mock_get_complaint_by_id(complain_id):
        return VALID_COMPLAINT if complain_id == 1 else None
    monkeypatch.setattr(auth_api_services, "get_complaint_by_id", mock_get_complaint_by_id)
    token = auth_api_services.create_access_token({"sub": "tester"})
    response = client.get("/rs_microservice/v2/complaint/get/1",
                          headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["data"]["complain_id"] == 1

# -------------------- JWT Token Edge Cases --------------------
def test_get_current_user_no_token():
    response = client.get("/rs_microservice/v2/complaint/get/1")
    assert response.status_code in (401, 403)

def test_jwt_token_invalid_signature(monkeypatch):
    token = create_access_token({"sub": "tester"}) + "abcd"
    response = client.get("/rs_microservice/v2/complaint/get/1",
                          headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

# -------------------- Login Endpoint --------------------
@pytest.mark.parametrize("payload, expected_status", [
    ({"username": "nosuch", "password": "wrong"}, 401),
    ({"username": "", "password": ""}, 401),
])
def test_login_invalid_credentials(payload, expected_status):
    response = client.post("/rs_microservice/v2/token", data=payload)
    assert response.status_code == expected_status

def test_login_missing_fields():
    response = client.post("/rs_microservice/v2/token", data={})
    assert response.status_code == 422


# -------------------- Create Complaint --------------------
def test_create_complaint_unauthenticated():
    response = client.post("/rs_microservice/v2/complaint/add", data={"name": "user"})
    assert response.status_code in (401, 403)

# -------------------- Update Complaint --------------------
def test_update_complaint_permission_denied(valid_token, monkeypatch):
    monkeypatch.setattr(auth_api_services, "get_complaint_by_id",
                        lambda cid: {"created_by": "otheruser"})
    response = client.patch("/rs_microservice/v2/complaint/update/1",
                            headers={"Authorization": f"Bearer {valid_token}"},
                            data={"name": "tester"})
    assert response.status_code == 403


# -------------------- File Helper --------------------
def create_test_file(filename="test.txt", content=b"hello"):
    return UploadFile(filename=filename, file=io.BytesIO(content))

# -------------------- Create/Update Complaint with Files --------------------
def test_create_complaint_with_files(monkeypatch, valid_token):
    monkeypatch.setattr("auth_api_services.create_complaint", lambda data: {"complain_id": 1, **data})
    monkeypatch.setattr("auth_api_services.get_complaint_by_id", lambda cid: {"complain_id": cid})
    monkeypatch.setattr("auth_api_services.upload_file_thread", lambda f, cid, user: True)
    monkeypatch.setattr("auth_api_services.send_plain_mail", lambda **kwargs: True)
    files = [("rail_sathi_complain_media_files", ("file1.txt", io.BytesIO(b"file1"), "text/plain"))]
    response = client.post("/rs_microservice/v2/complaint/add",
                           headers={"Authorization": f"Bearer {valid_token}"},
                           data={"name": "tester", "mobile_number": "12345"},
                           files=files)
    assert response.status_code == 200
    assert response.json()["data"]["complain_id"] == 1

def test_update_complaint_with_files(monkeypatch, valid_token):
    monkeypatch.setattr("auth_api_services.get_complaint_by_id",
                        lambda cid: {"created_by": "tester", "mobile_number": "123", "complain_status": "pending"})
    monkeypatch.setattr("auth_api_services.update_complaint", lambda cid, data: {"complain_id": cid, **data})
    monkeypatch.setattr("auth_api_services.upload_file_thread", lambda f, cid, user: True)
    files = [("rail_sathi_complain_media_files", ("file2.txt", io.BytesIO(b"file2"), "text/plain"))]
    response = client.patch("/rs_microservice/v2/complaint/update/1",
                            headers={"Authorization": f"Bearer {valid_token}"},
                            data={"name": "tester", "mobile_number": "123"},
                            files=files)
    assert response.status_code == 200
    assert response.json()["data"]["complain_id"] == 1

def test_create_complaint_without_files(monkeypatch, valid_token):
    monkeypatch.setattr(auth_api_services, "create_complaint", lambda data: {"complain_id": 1, **data})
    response = client.post("/rs_microservice/v2/complaint/add",
                           headers={"Authorization": f"Bearer {valid_token}"},
                           data={"name": "tester", "mobile_number": "12345"})
    assert response.status_code == 200


# -------------------- War Room Email Logic --------------------
mock_conn = MagicMock()
def test_create_complaint_war_room_email(monkeypatch, valid_token):
    monkeypatch.setattr("auth_api_services.create_complaint", lambda data: {"complain_id": 1, **data})
    monkeypatch.setattr("auth_api_services.get_complaint_by_id", lambda cid: {"complain_id": cid})
    monkeypatch.setattr("auth_api_services.execute_query", lambda conn, query, params=None: [])
    monkeypatch.setattr("auth_api_services.get_db_connection", lambda: mock_conn)
    monkeypatch.setattr("auth_api_services.send_plain_mail", lambda **kwargs: True)
    monkeypatch.setattr("auth_api_services.upload_file_thread", lambda f, cid, user: True)
    response = client.post("/rs_microservice/v2/complaint/add",
                           headers={"Authorization": f"Bearer {valid_token}"},
                           data={"name": "tester", "mobile_number": "123", "train_number": "1234"})
    assert response.status_code == 200

# -------------------- Exception Handling --------------------
def test_get_complaint_raises_exception(monkeypatch, valid_token):
    def raise_exc(cid):
        raise Exception("DB error")
    monkeypatch.setattr("auth_api_services.get_complaint_by_id", raise_exc)
    response = client.get("/rs_microservice/v2/complaint/get/1",
                          headers={"Authorization": f"Bearer {valid_token}"})
    assert response.status_code == 500

def test_create_access_token_fallback_secret(monkeypatch):
    monkeypatch.setattr("auth_api_services.os", type("os", (), {"getenv": lambda k, default=None: default})())
    token = create_access_token({"sub": "user"})
    decoded = jwt.decode(token, auth_api_services.SECRET_KEY, algorithms=["HS256"])
    assert decoded["sub"] == "user"

# -------------------- PUT / Replace Complaint --------------------
def test_replace_complaint_permission_denied(monkeypatch, valid_token):
    monkeypatch.setattr("auth_api_services.get_complaint_by_id",
                        lambda cid: {"created_by": "otheruser", "complain_status": "pending"})
    response = client.put("/rs_microservice/v2/complaint/update/1",
                          headers={"Authorization": f"Bearer {valid_token}"},
                          data={"name": "tester"})
    assert response.status_code == 403

#------------------------DELETE--------------------------------
@patch("auth_api_services.get_complaint_by_id")
@patch("auth_api_services.delete_complaint")
@patch("auth_api_services.get_current_user")
def test_delete_complaint_success(mock_user, mock_delete, mock_get):
    mock_user.return_value = {"username": "test_user"}
    mock_get.return_value = {
        "id": 1,
        "created_by": "test_user",
        "complain_status": "pending",
        "mobile_number": "1234567890"
    }

    response = client.delete(
        "/complaint/delete/1",
        data={"name": "Asad", "mobile_number": "1234567890"}
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Complaint deleted successfully"}
    mock_delete.assert_called_once_with(1)


@patch("auth_api_services.get_complaint_by_id")
@patch("auth_api_services.get_current_user")
def test_delete_complaint_not_found(mock_user, mock_get):
    mock_user.return_value = {"username": "test_user"}
    mock_get.return_value = None  # complaint not found

    response = client.delete(
        "/complaint/delete/99",
        data={"name": "Asad", "mobile_number": "1234567890"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Complaint not found"


@patch("auth_api_services.get_complaint_by_id")
@patch("auth_api_services.get_current_user")
def test_delete_complaint_forbidden_wrong_user(mock_user, mock_get):
    mock_user.return_value = {"username": "other_user"}
    mock_get.return_value = {
        "id": 1,
        "created_by": "test_user",
        "complain_status": "pending",
        "mobile_number": "1234567890"
    }

    response = client.delete(
        "/complaint/delete/1",
        data={"name": "Asad", "mobile_number": "1234567890"}
    )

    assert response.status_code == 403
    assert "Only user who created the complaint can delete it." in response.text


@patch("auth_api_services.get_complaint_by_id")
@patch("auth_api_services.get_current_user")
def test_delete_complaint_forbidden_completed_status(mock_user, mock_get):
    mock_user.return_value = {"username": "test_user"}
    mock_get.return_value = {
        "id": 1,
        "created_by": "test_user",
        "complain_status": "completed",
        "mobile_number": "1234567890"
    }

    response = client.delete(
        "/complaint/delete/1",
        data={"name": "Asad", "mobile_number": "1234567890"}
    )

    assert response.status_code == 403


@patch("auth_api_services.get_complaint_by_id")
@patch("auth_api_services.get_current_user")
def test_delete_complaint_forbidden_mobile_mismatch(mock_user, mock_get):
    mock_user.return_value = {"username": "test_user"}
    mock_get.return_value = {
        "id": 1,
        "created_by": "test_user",
        "complain_status": "pending",
        "mobile_number": "9999999999"
    }

    response = client.delete(
        "/complaint/delete/1",
        data={"name": "Asad", "mobile_number": "1234567890"}
    )

    assert response.status_code == 403


# -------------------- GET Complaints by Date --------------------
def test_get_complaints_by_date_invalid_date(monkeypatch, valid_token):
    response = client.get("/rs_microservice/v2/complaint/get/date/2025-31-12",
                          headers={"Authorization": f"Bearer {valid_token}"},
                          params={"mobile_number": "123"})
    assert response.status_code == 400

def test_get_complaints_by_date_missing_mobile(monkeypatch, valid_token):
    response = client.get("/rs_microservice/v2/complaint/get/date/2025-08-22",
                          headers={"Authorization": f"Bearer {valid_token}"})
    assert response.status_code == 400

def test_get_complaints_by_date_success(monkeypatch, valid_token):
    monkeypatch.setattr("auth_api_services.get_complaints_by_date", lambda date, mobile: [{"complain_id": 1}])
    response = client.get("/rs_microservice/v2/complaint/get/date/2025-08-22",
                          headers={"Authorization": f"Bearer {valid_token}"},
                          params={"mobile_number": "123"})
    assert response.status_code == 200
    assert response.json()[0]["complain_id"] == 1

# -------------------- Login Failures --------------------
@patch("auth_api_services.get_db_connection")
@patch("auth_api_services.execute_query")
def test_login_user_not_found(mock_exec, mock_conn):
    mock_conn.return_value = MagicMock()
    mock_exec.return_value = []
    response = client.post("/rs_microservice/v2/token", data={"username": "nouser", "password": "pwd"})
    assert response.status_code == 401

@patch("auth_api_services.get_db_connection")
@patch("auth_api_services.execute_query")
def test_login_wrong_password(mock_exec, mock_conn):
    mock_conn.return_value = MagicMock()
    mock_exec.return_value = [{"username": "john", "password": auth_api_services.django_pbkdf2_sha256.hash("secret")}]
    response = client.post("/rs_microservice/v2/token", data={"username": "john", "password": "wrong"})
    assert response.status_code == 401

# -------------------- JWT Edge Cases --------------------
def test_get_current_user_missing_sub(monkeypatch):
    token = auth_api_services.create_access_token({"foo": "bar"})
    with pytest.raises(HTTPException):
        auth_api_services.get_current_user(token)
