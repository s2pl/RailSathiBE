# Complaint Microservice – FastAPI

A FastAPI-based microservice that handles user authentication (JWT, Signup, Update, Create etc.) and complaint management for the RailSathi backend.

## Features
- Realtime Complaint Resolution System for running trains.
  
## Installation

## Prerequisites
- Python 3.7+
- pip

### Setup

1. **Clone the repository**
```bash
git clone https://github.com/s2pl/RailSathiBE.git
cd RailSathiBE
```

2. **Create virtual environment**

```bash
python -m venv venv
source venv/bin/activate # On Windows: venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```
4. **Configure environment variables**
Create a `.env` file:
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=your-email@gmail.com

5. **Run the service**

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```


## API Documentation

The complete, interactive API documentation (Swagger UI) is available at:
- UAT: [https://rsuatapi.suvidhaen.com/rs_microservice/docs] (https://rsuatapi.suvidhaen.com/rs_microservice/docs)
- Production: [https://rsapi.suvidhaen.com/rs_microservice/docs] (https://rsapi.suvidhaen.com/rs_microservice/docs)
