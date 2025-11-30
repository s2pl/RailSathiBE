# passenger_feedback/routes.py

from fastapi import APIRouter, Query, HTTPException
import requests

router = APIRouter(
    prefix="/feedback",                # all endpoints will start with /feedback
    tags=["Public Passenger Feedback"]
)


@router.get("/pnr-info")
def get_pnr_details(pnr: str = Query(..., min_length=10, max_length=10)):

    railops_url = (
        "https://railopsapi.biputri.com/"
        f"pnr_microservice/check_pnr_status?pnr={pnr}"
    )

    try:
        response = requests.get(railops_url, timeout=8)
        
        return response.json()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching PNR details: {str(e)}"
        )



@router.post("/submit")
def submit_feedback_to_railops(payload: dict):
    """
    Public API.
    Takes complaint/feedback body from frontend and forwards it to RailOps.
    """
    railops_url = "https://railopsapi.biputri.com/rs_microservice/complaint/add"

    try:
        response = requests.post(railops_url, json=payload, timeout=15)
        
        return response.json()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to submit complaint: {str(e)}"
        )
