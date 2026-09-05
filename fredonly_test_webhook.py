import requests

base_url = "http://127.0.0.1:8000"

# 1. Fund wallet for testing user
print("Funding wallet...")
r_fund = requests.post(f"{base_url}/api/v1/wallet/fund", json={"user_id": "william_123", "amount_ngn": 2000.0})
print("Fund Response:", r_fund.json())

# 2. Rent a number for Match
print("Renting a virtual number for Match...")
rent_res = requests.post(f"{base_url}/api/v1/numbers/rent", json={"user_id": "william_123", "service_name": "Match"})
rent_data = rent_res.json()

if rent_res.status_code != 200:
    print("Rental failed:", rent_data)
    exit()

phone_number = rent_data["phone_number"]
print(f"Successfully rented number: {phone_number}")

# 3. Simulate incoming SMS webhook from Match
print("Simulating incoming SMS webhook...")
webhook_payload = {
    "From": "Match.com",
    "To": phone_number,
    "Body": "Your Match verification code is 592810. Do not share this code."
}

webhook_res = requests.post(f"{base_url}/api/v1/sms/webhook/incoming", data=webhook_payload)
print("Webhook Raw Status Code:", webhook_res.status_code)
print("Webhook Raw Response Text:", webhook_res.text)

# 4. Fetch Inbox
inbox_res = requests.get(f"{base_url}/api/v1/sms/inbox/{phone_number}")
print("\nFetched Inbox Data:", inbox_res.json())
