import requests

base_url = "http://127.0.0.1:8000"

target_phone = input("Enter the active phone number from your dashboard: ").strip()

print(f"Sending simulated incoming SMS to {target_phone}...")
webhook_payload = {
    "From": "Match.com",
    "To": target_phone,
    "Body": "Your Match verification code is 884219. Do not share this code."
}

res = requests.post(f"{base_url}/api/v1/sms/webhook/incoming", data=webhook_payload)
print("Webhook Response:", res.json())
print("Check your browser dashboard inbox—the OTP code should appear within 3 seconds!")
