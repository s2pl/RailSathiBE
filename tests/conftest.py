import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# tests/conftest.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from passlib.hash import django_pbkdf2_sha256
from datetime import datetime
import os
from dotenv import load_dotenv

from main import app
from database import get_db_connection, execute_query

# Auto-load env file
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

import os
import psycopg2

from dotenv import load_dotenv

# Load DB credentials
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

@pytest.fixture
def db_conn():
    conn = get_db_connection()
    yield conn
    conn.close()





@pytest.fixture
def setup_test_user(db_conn):
    password = django_pbkdf2_sha256.hash("testpass")

    execute_query(
        db_conn,
        """
        INSERT INTO user_onboarding_user
            (id, username, password, first_name, last_name, email, phone,
             is_active, created_at, updated_at, created_by)
        VALUES
            (999, 'testuser', %s, 'Test', 'User', 'testuser@example.com',
             '9999999999', true, %s, %s, 1)
        ON CONFLICT (id) DO NOTHING
        """,
        (password, datetime.utcnow(), datetime.utcnow()),
    )
    db_conn.commit()

    yield

    execute_query(db_conn, "DELETE FROM user_onboarding_user WHERE id=999")
    db_conn.commit()

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def auth_token(client, setup_test_user):
    resp = await client.post(
        "/rs_microservice/v2/token",
        data={"username": "testuser", "password": "testpass"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]
