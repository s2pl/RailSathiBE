# passenger_feedback/routes.py

from fastapi import APIRouter, Query, HTTPException, Request
import requests

router = APIRouter(prefix="/feedback", tags=["Public Passenger Feedback"])


# 1️⃣ Check PNR → Detect Train + Depot → Return Form based on Depot
@router.get("/pnr-info")
async def get_pnr_details(pnr: str = Query(..., min_length=10, max_length=10)):
    railops_url = f"https://railopsapi.biputri.com/pnr_microservice/check_pnr_status?pnr={pnr}"

    try:
        response = requests.get(railops_url, timeout=8)
        data = response.json()

        # If PNR is valid → Auto depot selection
        if response.status_code == 200 and data.get("train_no"):
            depot = data.get("depot") or "UNKNOWN_DEPOT"

            return {
                "success": True,
                "mode": "auto",
                "message": "PNR valid - depot detected automatically",
                "train_no": data.get("train_no"),
                "depot": depot,
                "allow_manual_entry": False,
                "feedback_form_fields": {
                    "required": ["feedback_text"],  # Only depot decides the form
                    "optional": ["image", "category"]
                }
            }

        # PNR invalid → User selects depot manually
        return {
            "success": False,
            "mode": "manual",
            "message": "Invalid PNR. Enter depot manually to continue.",
            "allow_manual_entry": True,
            "feedback_form_fields": {
                "required": ["depot", "feedback_text"],
                "optional": ["image", "category"]
            }
        }

    except:
        return {
            "success": False,
            "mode": "manual",
            "message": "PNR lookup failed. Use manual depot entry.",
            "allow_manual_entry": True
        }



# 2️⃣ Submit Feedback – Auto fill name/phone if logged in
@router.post("/submit")
async def submit_feedback(request: Request, payload: dict):

    # check user login status
    user = request.state.user if hasattr(request.state, "user") else None

    # If logged in → auto-fill name + phone (no need to ask from UI)
    if user:
        payload["name"] = user.name
        payload["mobile_number"] = user.mobile
    else:
        # guest users must send name + phone manually
        if "name" not in payload or "mobile_number" not in payload:
            raise HTTPException(status_code=400, detail="Name & Mobile required for guest users")

    # Depot is mandatory for feedback form
    if "train_depot" not in payload:
        raise HTTPException(status_code=400, detail="Depot is required to submit feedback")

    # Feedback API forward to RailOps
    railops_url = "https://railopsapi.biputri.com/rs_microservice/complaint/add"
    
    try:
        response = requests.post(railops_url, data=payload)  # <-- will shift to multipart later
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback submit failed: {str(e)}")
