# passenger_feedback/routes.py

from fastapi import APIRouter, Query, HTTPException
import requests

router = APIRouter(
    prefix="/feedback",
    tags=["Public Passenger Feedback"]
)


# If PNR is invalid → Allows manual entry of train & depot
@router.get("/pnr-info")
def get_pnr_details(pnr: str = Query(..., min_length=10, max_length=10)):
    railops_url = f"https://railopsapi.biputri.com/pnr_microservice/check_pnr_status?pnr={pnr}"

    try:
        response = requests.get(railops_url, timeout=8)
        data = response.json()

        # VALID PNR → fetch train automatically
        if response.status_code == 200 and data.get("train_no"):
            return {
                "success": True,
                "mode": "auto",
                "message": "Valid PNR. Train details fetched successfully.",
                "data": {
                    "train_no": data.get("train_no"),
                    "date_of_journey": data.get("date_of_journey"),
                    "coach": data.get("passengers", [{}])[0].get("coach") if data.get("passengers") else None
                },
                "allow_manual_entry": False  # 🚫 user doesn't need to enter manually
            }

        # INVALID PNR → user may enter train & depot manually
        return {
            "success": False,
            "mode": "manual",
            "message": "Invalid PNR. Enter Train Number & Depot manually.",
            "allow_manual_entry": True  # 🟢 frontend will show manual input boxes
        }

    except:
        return {
            "success": False,
            "mode": "manual",
            "message": "PNR service unreachable. Enter Train Number & Depot manually.",
            "allow_manual_entry": True
        }


@router.post("/submit")
def submit_feedback_to_railops(payload: dict):
    railops_url = "https://railopsapi.biputri.com/rs_microservice/complaint/add"

    try:
        response = requests.post(railops_url, json=payload, timeout=15)
        return response.json() 

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to submit complaint: {str(e)}"
        )
