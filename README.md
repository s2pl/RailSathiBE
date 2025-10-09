Complaint Microservice – FastAPI

A FastAPI-based microservice that handles user authentication (JWT, Signup, Update, Create etc.) and complaint management for the RailSathi backend.

Features
Authentication System
JWT token-based authentication
Create, update, and view complaints etc.
Complaints are linked to authenticated users
Installation
Prerequisites
Python 3.7+
pip
Setup
Clone the repository
git clone https://github.com/s2pl/RailSathi_be.git
cd RailSathi_be
Create virtual environment
python -m venv venv
source venv/bin/activate # On Windows: venv\Scripts\activate
Install dependencies
pip install -r requirements.txt
Configure environment variables Create a .env file: SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=your-email@gmail.com SMTP_PASSWORD=your-app-password FROM_EMAIL=your-email@gmail.com

Run the service

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
API Documentation
The complete, interactive API documentation (Swagger UI) is available at:

UAT: https://rsuatapi.suvidhaen.com/rs_microservice/docs
Production: https://rsapi.suvidhaen.com/rs_microservice/docs
