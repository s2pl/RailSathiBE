from utils.email_utils import send_plain_mail, EMAIL_SENDER
from unittest.mock import patch, MagicMock
import pytest

# Add this test function and call it directly
@patch("utils.email_utils.FastMail.send_message", return_value=True)
def test_direct_email(mock_send):
    
    success = send_plain_mail(
        subject="Test Email",
        message="This is a test email",
        from_=EMAIL_SENDER,
        to=["harshnmishra01@gmail.com"]
    )
    assert success
    mock_send.assert_called_once()

# Call this function to test
test_direct_email()

# test_email.py
import pytest
from unittest.mock import patch, AsyncMock
from utils.email_utils import send_passenger_complain_email

@patch("utils.email_utils.FastMail.send_message", new_callable=AsyncMock)
def test_passenger_email(mock_send):
    mock_send.return_value = True

    # Make sure at least one user matches
    complain_details = {
        "complain_id": 123,
        "train_no": "12345",
        "train_name": "Express",
        "user_phone_number": "9876543210",
        "passenger_name": "Test Passenger",
        "berth": "A1",
        "coach": "B",
        "pnr": "PNR123",
        "description": "Test complaint",
        "train_depo": "Depot1",
        "created_at": "2025-08-30",
        "date_of_journey": "2025-08-31"
    }

    # Patch DB query to return a user
    with patch("utils.email_utils.execute_query") as mock_query:
        mock_query.return_value = [{"email": "test@example.com"}]  # ensure send_mail runs
        result = send_passenger_complain_email(complain_details)

    assert result["status"] == "success"
    mock_send.assert_called()

