# Add this test function and call it directly
def test_direct_email():
    from utils.email_utils import send_plain_mail, EMAIL_SENDER
    
    success = send_plain_mail(
        subject="Test Email",
        message="This is a test email",
        from_=EMAIL_SENDER,
        to=["harshnmishra01@gmail.com"]
    )
    print(f"Email test result: {success}")

# Call this function to test
test_direct_email()