from fastapi_mail import ConnectionConfig
from pydantic_settings import BaseSettings
from pydantic import EmailStr
import os

class Settings(BaseSettings):
    MAIL_USERNAME: str
    MAIL_PASSWORD: str  
    MAIL_FROM: EmailStr
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_FROM_NAME: str = "RailSathi"
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    USE_CREDENTIALS: bool = True
    VALIDATE_CERTS: bool = True
    
    # Database configuration
    postgres_host: str
    postgres_port: str = "5432"
    postgres_user: str
    postgres_password: str
    postgres_db: str
    
    # App configuration
    app_host: str = "0.0.0.0"
    app_port: str = "8000"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=settings.USE_CREDENTIALS,
    VALIDATE_CERTS=settings.VALIDATE_CERTS,
    TEMPLATE_FOLDER=os.path.join(os.getcwd(), 'templates')
)