# Complaint Microservice – FastAPI

A FastAPI-based microservice that handles user authentication (JWT, Signup, Update, Create etc.) and complaint management for the RailSathi backend.

## Features
- Authentication System
- JWT token-based authentication
- Create, update, and view complaints etc.
- Complaints are linked to authenticated users
  
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
- UAT: [https://rsuatapi.suvidhaen.com/rs_microservice/docs] (https://rsuatapi.suvidhaen.com/rs_microservice/docs).
- Production: [https://rsapi.suvidhaen.com/rs_microservice/docs] (https://rsapi.suvidhaen.com/rs_microservice/docs)

## Quick Start

Send a POST request to `/rs_microservice/v2/complaint/add/`:

Response Body
{
  "message": "Complaint created successfully",
  "data": {
    "complain_id": 395,
    "pnr_number": "1234567890",
    "is_pnr_validated": "not-attempted",
    "name": "raj",
    "mobile_number": "8517078080",
    "complain_type": "cleaning",
    "complain_description": "dirty coach",
    "complain_date": "2025-08-22",
    "complain_status": "pending",
    "coach": "S2",
    "berth_no": 4,
    "created_at": "2025-10-09T13:55:59.470375+00:00",
    "updated_at": "2025-10-09T13:55:59.470375+00:00",
    "created_by": "asad",
    "train_id": 1,
    "updated_by": null,
    "train_name": null,
    "train_number": "12256",
    "submission_status": null,
    "train_no": null,
    "train_depot": "(Not found in database)",
    "rail_sathi_complain_media_files": [],
    "customer_care": "9123183988"
  }
}
