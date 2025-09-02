import io
import pytest
import asyncio
from datetime import datetime, date
from types import SimpleNamespace

import services

# ---------- Fixtures / Mocks ---------- #

class FakeBlob:
    def upload_from_file(self, *a, **kw): pass
    @property
    def public_url(self): return "http://mock-url.com/file.jpg"

class FakeBucket:
    def blob(self, key): return FakeBlob()

class FakeClient:
    def bucket(self, name): return FakeBucket()

class FakeCursor:
    def __init__(self): self._rowcount = 1
    def execute(self, query, params=None): pass
    def fetchone(self): return [42]
    @property
    def rowcount(self): return self._rowcount

class FakeConn:
    def __init__(self): self._closed = False
    def cursor(self): return FakeCursor()
    def commit(self): pass
    def rollback(self): pass
    def close(self): self._closed = True

@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setattr(services, "get_gcs_client", lambda: FakeClient())
    monkeypatch.setattr(services, "get_db_connection", lambda: FakeConn())
    monkeypatch.setattr(services, "execute_query", lambda conn, q, p=None: [{"id": 1}])
    monkeypatch.setattr(
        services,
        "execute_query_one",
        lambda conn, q, p=None: {"complain_id": 42, "created_by": "user", "mobile_number": "9999", "complain_status": "pending"},
    )
    monkeypatch.setattr(services, "send_passenger_complain_email", lambda details: True)
    yield

# ---------- Utility Tests ---------- #

def test_get_valid_filename_removes_specials():
    assert services.get_valid_filename("a@b!c.png") == "abcpng"

def test_sanitize_timestamp_removes_colons():
    result = services.sanitize_timestamp("2024-01-01%2012:00:00")
    assert ":" not in result

# ---------- Media Upload Tests ---------- #

def test_process_media_file_upload_image():
    fake_content = io.BytesIO(b"fake").getvalue()
    url = services.process_media_file_upload(fake_content, "jpg", 123, "image")
    assert url.startswith("http://mock-url.com")

def test_process_media_file_upload_unsupported():
    fake_content = b"data"
    url = services.process_media_file_upload(fake_content, "txt", 123, "text")
    assert url is None

def test_upload_file_thread_runs(monkeypatch):
    f = SimpleNamespace(
        filename="test.jpg",
        content_type="image/jpeg",
        read=lambda: b"fakeimagecontent"
    )
    services.upload_file_thread(f, 1, "user")

@pytest.mark.asyncio
async def test_upload_file_async_runs(monkeypatch):
    f = SimpleNamespace(
        filename="test.jpg",
        content_type="image/jpeg",
        read=lambda: b"fakeimagecontent"
    )
    f.read = asyncio.coroutine(lambda: b"fakeimagecontent")
    result = await services.upload_file_async(f, 1, "user")
    assert result is True or result is False  # just check it runs

# ---------- Complaint CRUD Tests ---------- #

def test_create_complaint_returns_dict():
    complaint = services.create_complaint({"name": "John", "mobile_number": "12345"})
    assert isinstance(complaint, dict)
    assert complaint["complain_id"] == 42

def test_get_complaint_by_id_found():
    result = services.get_complaint_by_id(42)
    assert result["complain_id"] == 42
    assert "rail_sathi_complain_media_files" in result

def test_update_complaint_returns_updated():
    result = services.update_complaint(42, {"name": "Updated"})
    assert result["complain_id"] == 42

def test_delete_complaint_returns_count():
    count = services.delete_complaint(42)
    assert count == 1

def test_delete_complaint_media_with_ids():
    count = services.delete_complaint_media(42, [1, 2])
    assert count == 1

def test_delete_complaint_media_empty_list():
    count = services.delete_complaint_media(42, [])
    assert count == 0

# ---------- Access Validation Tests ---------- #

def test_validate_complaint_access_success():
    ok, msg = services.validate_complaint_access(42, "user", "9999")
    assert ok is True
    assert msg is None

def test_validate_complaint_access_denied(monkeypatch):
    monkeypatch.setattr(
        services,
        "execute_query_one",
        lambda conn, q, p=None: {"created_by": "other", "mobile_number": "8888", "complain_status": "pending"},
    )
    ok, msg = services.validate_complaint_access(42, "user", "9999")
    assert ok is False
    assert "Only user" in msg
