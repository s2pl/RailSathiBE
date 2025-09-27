import os
import logging
from typing import List, Dict, Any, Optional
import requests
from datetime import datetime
import threading  # Added for threaded (non-blocking) push send

logger = logging.getLogger(__name__)

# Mapping environments to base URLs (adjust as per actual deployments)
ENV_NOTIFICATION_BASE = {
    "LOCAL": "http://localhost:8000",
    "UAT": os.getenv("UAT_API_NOTIFICATION", "https://railops-uat-api.biputri.com"),
    "PROD": os.getenv("PROD_API_NOTIFICATION", "https://railopsapi.biputri.com"),
}

def get_env() -> str:
    return os.getenv("ENV", "LOCAL").upper()

def get_notification_base_url() -> str:
    env = get_env()
    return ENV_NOTIFICATION_BASE.get(env, ENV_NOTIFICATION_BASE["LOCAL"])  # fallback local


def build_passenger_complaint_notification(
    tokens: List[str],
    complaint: Dict[str, Any]
) -> Dict[str, Any]:
    """Build push notification payload for passenger complaint.
    """
    # Normalize keys (support both naming variants)
    def g(*names, default=""):
        for n in names:
            if n in complaint and complaint[n] not in (None, ""):
                return complaint[n]
        return default

    complain_id = str(g("complain_id", "complaint_id", default=""))
    passenger_name = g("passenger_name")
    passenger_phone = g("user_phone_number", "passenger_phone")
    train_no = g("train_no", "train_number")
    train_name = g("train_name")
    coach = g("coach")
    berth = str(g("berth", "berth_no"))
    pnr = g("pnr", default="PNR not provided by passenger")
    description = g("description", "complaint_text")
    train_depo = g("train_depo", "train_depot", "depot")
    priority = g("priority", default="normal")
    date_of_journey = g("date_of_journey", "commencement_date")

    # Format created_at / submitted date
    created_at_raw = g("created_at", "submitted_date")
    created_at_display = created_at_raw
    if created_at_raw:
        # Try a few common formats; keep raw if parsing fails
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y, %H:%M"):
            try:
                dt = datetime.strptime(created_at_raw, fmt)
                created_at_display = dt.strftime("%d %b %Y, %H:%M")
                break
            except ValueError:
                continue

    title = f"🚨 Railsathi Complaint - {train_no} ({coach} - {berth}) "

    body_lines = [
        f"👤 Name: {passenger_name} | {passenger_phone}",
        f"🚂 Train: {train_no} | {coach}/{berth}",
        f"📝 Complaint: {description}",
    ]
    if priority.lower() in ("high", "urgent"):
        body_lines.append("⚠️ IMMEDIATE ACTION REQUIRED")
    body = "\n" + "\n".join(body_lines)

    data_payload = {
        "notification_type": "passenger_complaint",
        "complaint_id": complain_id,
        "submitted_date": created_at_display,
        "passenger_name": passenger_name,
        "passenger_phone": passenger_phone,
        "train_number": train_no,
        "train_name": train_name,
        "commencement_date": date_of_journey,
        "coach": coach,
        "berth": berth,
        "pnr": pnr,
        "complaint_text": description,
        "depot": train_depo,
        "priority": priority,
        "action_required": str(priority.lower() in ("high", "urgent")).lower(),
        "deep_link": f"railops://complaints/{complain_id}",
        "screen": "complaint_details",
    }

    def _ensure_all_strings(obj: Any) -> Any:
        """Recursively convert all non-dict/list primitives to strings.
        - None -> ""
        - Dict keys forced to str
        - Lists values converted element-wise
        """
        if isinstance(obj, dict):
            return {str(k): ("" if v is None else str(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return ["" if v is None else str(v) for v in obj]
        return "" if obj is None else str(obj)

    # Ensure tokens list elements are strings & non-empty
    safe_tokens = [str(t) for t in tokens if t]
    normalized_data = _ensure_all_strings(data_payload)

    return {
        "tokens": safe_tokens,
        "title": _ensure_all_strings(title),
        "body": _ensure_all_strings(body),
        "data": normalized_data,
        "notification_type": "default"
    }


def send_push_notification(payload: Dict[str, Any], timeout: int = 10) -> Optional[Dict[str, Any]]:
    """POST the push notification payload to notification service.
    Returns response JSON or None.
    """
    base_url = get_notification_base_url()
    url = f"{base_url.rstrip('/')}/notification/push/"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            logger.warning("Notification service returned non-JSON response")
            return {"status": resp.status_code, "text": resp.text}
    except Exception as e:
        logger.error(f"Failed to send push notification: {e}")
        return None


def send_passenger_complaint_notification(tokens: List[str], complaint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = build_passenger_complaint_notification(tokens, complaint)
    return send_push_notification(payload)


def send_passenger_complaint_notification_in_thread(tokens: List[str], complaint: Dict[str, Any]) -> bool:
    """Fire-and-forget threaded sender for passenger complaint notifications.
    Returns True if thread started. Logs result inside thread.
    """
    payload = build_passenger_complaint_notification(tokens, complaint)

    def _worker():
        try:
            resp = send_push_notification(payload)
            logger.info(
                f"[Push][Thread] Complaint {payload['data'].get('complaint_id')} notification sent | resp={resp}"
            )
        except Exception as e:
            logger.error(
                f"[Push][Thread] Failed to send complaint {payload['data'].get('complaint_id')} notification: {e}"
            )

    try:
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return True
    except Exception as e:
        logger.error(f"[Push][Thread] Could not start push notification thread: {e}")
        return False



# In-App Notification Helpers 
def build_passenger_complaint_in_app_notification(tokens: List[str], complaint: Dict[str, Any]) -> Dict[str, Any]:
    """Build the in-app notification payload (as required by /notification/in-app/ endpoint)
    reusing the push notification builder so that data normalization logic stays in one place.

    Returned structure example:
    {
        "tokens": [...],
        "title": str,
        "body": str,
        "notif_type": "passenger_complaint",
        "notification_type": "passenger_complaint",
        "extra_data": {...}  # (the data payload from push builder)
    }
    """
    push_payload = build_passenger_complaint_notification(tokens, complaint)
    data = push_payload.get("data", {}) or {}
    notif_type = data.get("notification_type", "passenger_complaint")
    return {
        "tokens": push_payload.get("tokens", []),
        "title": push_payload.get("title", ""),
        "body": push_payload.get("body", ""),
        "notif_type": notif_type,
        "notification_type": notif_type,
        "extra_data": data,
    }


def send_in_app_notification(payload: Dict[str, Any], timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Send a generic in-app notification payload to /notification/in-app/ endpoint.
    Mirrors send_push_notification but targets the in-app route and expects the payload
    schema defined in build_passenger_complaint_in_app_notification.
    """
    base_url = get_notification_base_url()
    url = f"{base_url.rstrip('/')}/notification/in-app/"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            logger.warning("In-app notification service returned non-JSON response")
            return {"status": resp.status_code, "text": resp.text}
    except Exception as e:
        logger.error(f"Failed to send in-app notification: {e}")
        return None


def send_passenger_complaint_in_app_notification(tokens: List[str], complaint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convenience wrapper to build & send passenger complaint in-app notification."""
    payload = build_passenger_complaint_in_app_notification(tokens, complaint)
    return send_in_app_notification(payload)


def send_passenger_complaint_in_app_notification_in_thread(tokens: List[str], complaint: Dict[str, Any]) -> bool:
    """Threaded fire-and-forget variant for in-app passenger complaint notification."""
    payload = build_passenger_complaint_in_app_notification(tokens, complaint)

    def _worker():
        try:
            resp = send_in_app_notification(payload)
            logger.info(
                f"[InApp][Thread] Complaint {payload['extra_data'].get('complaint_id')} in-app notification sent | resp={resp}"
            )
        except Exception as e:
            logger.error(
                f"[InApp][Thread] Failed to send complaint {payload['extra_data'].get('complaint_id')} in-app notification: {e}"
            )

    try:
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return True
    except Exception as e:
        logger.error(f"[InApp][Thread] Could not start in-app notification thread: {e}")
        return False



# Combined Push + In-App      

def send_passenger_complaint_push_and_in_app(tokens: List[str], complaint: Dict[str, Any]) -> Dict[str, Any]:
    """Send BOTH push and in-app notifications for a passenger complaint.

    Returns a dict summarizing results:
    {
        "push": <response_or_none>,
        "in_app": <response_or_none>,
        "success": bool  # True if at least one succeeded
    }
    """
    push_payload = build_passenger_complaint_notification(tokens, complaint)
    in_app_payload = build_passenger_complaint_in_app_notification(tokens, complaint)

    push_resp = send_push_notification(push_payload)
    in_app_resp = send_in_app_notification(in_app_payload)

    success = any(r is not None for r in (push_resp, in_app_resp))
    if not success:
        logger.error(
            f"[Combined] Failed to send both push and in-app for complaint {in_app_payload['extra_data'].get('complaint_id')}"  # type: ignore
        )
    else:
        logger.info(
            f"[Combined] Complaint {in_app_payload['extra_data'].get('complaint_id')} push={push_resp is not None} in_app={in_app_resp is not None}"  # type: ignore
        )

    return {"push": push_resp, "in_app": in_app_resp, "success": success}


def send_passenger_complaint_push_and_in_app_in_thread(tokens: List[str], complaint: Dict[str, Any]) -> bool:
    """Threaded variant: dispatch both push and in-app notifications in background.
    Returns True if thread started.
    """
    def _worker():
        try:
            result = send_passenger_complaint_push_and_in_app(tokens, complaint)
            logger.info(
                f"[Combined][Thread] Complaint notification dispatched result={result}"  # noqa: E501
            )
        except Exception as e:
            logger.error(
                f"[Combined][Thread] Failed to send combined notifications: {e}"
            )

    try:
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return True
    except Exception as e:
        logger.error(f"[Combined][Thread] Could not start combined notification thread: {e}")
        return False

__all__ = [
    "build_passenger_complaint_notification",
    "send_passenger_complaint_notification",
    "send_passenger_complaint_notification_in_thread",
    "send_push_notification",
    # In-app helpers
    "build_passenger_complaint_in_app_notification",
    "send_in_app_notification",
    "send_passenger_complaint_in_app_notification",
    "send_passenger_complaint_in_app_notification_in_thread",
    # Combined helpers
    "send_passenger_complaint_push_and_in_app",
    "send_passenger_complaint_push_and_in_app_in_thread",
    "get_notification_base_url"
]
