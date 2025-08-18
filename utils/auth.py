import os
import functools
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, OAuth2PasswordRequestForm, HTTPBearer
from jose import jwt, JWTError


SECRET_KEY = os.getenv("JWT_SECRET_KEY", "fallback_dummy_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

from fastapi.security import OAuth2PasswordBearer

bearer_scheme = HTTPBearer()

fake_user = {"username": "uday", "password": "2004"}

def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=30)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    token = credentials.credentials  # Extract token string
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {"username": username}
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    

def user_authentication(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        request: Request = kwargs.get("request") or args[0]
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Not authenticated")

        token = auth_header.split(" ")[1]
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            if username is None:
                raise HTTPException(status_code=401, detail="Invalid token")
            kwargs["current_user"] = {"username": username}
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return await func(*args, **kwargs)

    return wrapper