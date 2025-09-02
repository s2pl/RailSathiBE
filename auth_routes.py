# auth_routes.py
from fastapi import APIRouter, Depends
from datetime import timedelta, datetime
import os
from jose import jwt

router = APIRouter(prefix="/rs_microservice/v2")

SECRET_KEY = os.getenv("JWT_SECRET_KEY","fallback_dummy_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=30)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
