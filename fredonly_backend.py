import os
import random
import sqlite3
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI(title="FredOnly SMS Marketplace Backend", version="3.0")

# Enable CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "fredonly_v3.db"

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    cursor = conn.cursor()
    
    # Wallets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            user_id TEXT PRIMARY KEY,
            balance_ngn REAL DEFAULT 0.0
        )
    """)
    
    # Transactions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            type TEXT,
            amount REAL,
            description TEXT,
            created_at TEXT
        )
    """)
    
    # Rentals table (supports activation_id for live mapping)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rentals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT,
            user_id TEXT,
            service_name TEXT,
            activation_id TEXT,
            created_at TEXT,
            active INTEGER DEFAULT 1
        )
    """)
    
    # Messages table for inbox storage
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT,
            sender TEXT,
            body TEXT,
            code TEXT,
            service TEXT
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

class FundRequest(BaseModel):
    user_id: str
    amount_ngn: float

class RentRequest(BaseModel):
    user_id: str
    service_name: str

@app.get("/api/v1/wallet/{user_id}")
def get_wallet(user_id: str):
    conn = sqlite3.connect(DB_FILE, timeout=15)
    cursor = conn.cursor()
    
    cursor.execute("SELECT balance_ngn FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    balance = row[0] if row else 0.0
    
    cursor.execute("SELECT type, amount, description FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
    tx_rows = cursor.fetchall()
    transactions = [{"type": r[0], "amount": r[1], "desc": r[2]} for r in tx_rows]
    
    conn.close()
    return {"user_id": user_id, "balance_ngn": balance, "transactions": transactions}

@app.post("/api/v1/wallet/fund")
def fund_wallet(payload: FundRequest):
    conn = sqlite3.connect(DB_FILE, timeout=15)
    cursor = conn.cursor()
    
    cursor.execute("SELECT balance_ngn FROM wallets WHERE user_id = ?", (payload.user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO wallets (user_id, balance_ngn) VALUES (?, ?)", (payload.user_id, payload.amount_ngn))
    else:
        new_balance = row[0] + payload.amount_ngn
        cursor.execute("UPDATE wallets SET balance_ngn = ? WHERE user_id = ?", (new_balance, payload.user_id))
        
    timestamp = datetime.utcnow().isoformat()
    cursor.execute("INSERT INTO transactions (user_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
                   (payload.user_id, "CREDIT", payload.amount_ngn, f"Funded wallet with ₦{payload.amount_ngn}", timestamp))
    
    conn.commit()
    cursor.execute("SELECT balance_ngn FROM wallets WHERE user_id = ?", (payload.user_id,))
    final_balance = cursor.fetchone()[0]
    conn.close()
    
    return {"status": "success", "new_balance_ngn": final_balance}

@app.post("/api/v1/numbers/rent")
def rent_virtual_number(payload: RentRequest):
    service_prices = {
        "WhatsApp": 400, "Telegram": 250, "Twitter / X": 450, "Instagram": 500,
        "Facebook": 350, "TikTok": 400, "Snapchat": 380, "Discord": 280,
        "Google / Gmail": 300, "Microsoft / Outlook": 320, "Apple ID": 450,
        "OpenAI / ChatGPT": 600, "Match": 350, "Tinder": 400, "Bumble": 380,
        "Binance": 550, "PayPal": 500, "Wise": 480, "CashApp": 600
    }
    
    price = service_prices.get(payload.service_name, 300)
    
    conn = sqlite3.connect(DB_FILE, timeout=15)
    cursor = conn.cursor()
    
    cursor.execute("SELECT balance_ngn FROM wallets WHERE user_id = ?", (payload.user_id,))
    row = cursor.fetchone()
    balance = row[0] if row else 0.0
    
    if balance < price:
        conn.close()
        raise HTTPException(status_code=402, detail="Insufficient wallet balance.")
        
    new_balance = balance - price
    cursor.execute("UPDATE wallets SET balance_ngn = ? WHERE user_id = ?", (new_balance, payload.user_id))
    
    timestamp = datetime.utcnow().isoformat()
    cursor.execute("INSERT INTO transactions (user_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)",
                   (payload.user_id, "DEBIT", price, f"Rented virtual number for {payload.service_name}", timestamp))
    
    # Live 5SIM API Integration
    SMS_PROVIDER_API_KEY = os.getenv("SMS_PROVIDER_API_KEY")
    phone_number = None
    activation_id = None
    
    if SMS_PROVIDER_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {SMS_PROVIDER_API_KEY}",
                "Accept": "application/json"
            }
            service_slug = payload.service_name.lower().replace(" / ", "").replace(" ", "").replace(" / gmail", "")
            if "whatsapp" in service_slug: service_slug = "whatsapp"
            elif "telegram" in service_slug: service_slug = "telegram"
            elif "discord" in service_slug: service_slug = "discord"
            elif "openai" in service_slug or "chatgpt" in service_slug: service_slug = "openai"
            else: service_slug = "other"
            
            url = f"https://5sim.net/v1/user/buy/activation/usa/any/{service_slug}"
            res = requests.get(url, headers=headers, timeout=15)
            
            if res.status_code == 200:
                data = res.json()
                phone_number = data.get("phone")
                activation_id = str(data.get("id"))
        except Exception as e:
            print("5SIM Connection error:", e)
            
    # Fallback mock generator if no key is present or API call fails
    if not phone_number:
        phone_number = f"+1800{random.randint(1000000, 9999999)}"
        activation_id = "mock_act_123"
        
        # Auto-inject mock SMS so testing works right away
        mock_code = str(random.randint(100000, 999999))
        mock_body = f"Your {payload.service_name} code is {mock_code}"
        cursor.execute("INSERT INTO messages (phone_number, sender, body, code, service) VALUES (?, ?, ?, ?, ?)",
                       (phone_number, "System-Mock", mock_body, mock_code, payload.service_name))

    cursor.execute("INSERT INTO rentals (phone_number, user_id, service_name, activation_id, created_at, active) VALUES (?, ?, ?, ?, ?, 1)",
                   (phone_number, payload.user_id, payload.service_name, activation_id, timestamp))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "phone_number": phone_number,
        "service": payload.service_name,
        "price_deducted": price,
        "new_balance": new_balance
    }

@app.get("/api/v1/sms/inbox/{phone_number}")
def get_sms_inbox(phone_number: str):
    conn = sqlite3.connect(DB_FILE, timeout=15)
    cursor = conn.cursor()
    
    cursor.execute("SELECT sender, body, code, service FROM messages WHERE phone_number = ? ORDER BY id DESC", (phone_number,))
    rows = cursor.fetchall()
    messages = [{"sender": r[0], "body": r[1], "code": r[2], "service": r[3]} for r in rows]
    
    # If no messages found locally yet, check 5SIM API status directly using activation_id
    if not messages:
        cursor.execute("SELECT activation_id, service_name FROM rentals WHERE phone_number = ? AND active = 1", (phone_number,))
        rental = cursor.fetchone()
        
        if rental and rental[0] and rental[0] != "mock_act_123":
            act_id = rental[0]
            SMS_PROVIDER_API_KEY = os.getenv("SMS_PROVIDER_API_KEY")
            if SMS_PROVIDER_API_KEY:
                try:
                    headers = {"Authorization": f"Bearer {SMS_PROVIDER_API_KEY}", "Accept": "application/json"}
                    res = requests.get(f"https://5sim.net/v1/user/check/{act_id}", headers=headers, timeout=10)
                    if res.status_code == 200:
                        order_data = res.json()
                        sms_list = order_data.get("sms", [])
                        if sms_list:
                            for sms in sms_list:
                                sender = sms.get("sender", "Service")
                                body = sms.get("text", "")
                                code = sms.get("code", "")
                                service = rental[1]
                                
                                cursor.execute("INSERT INTO messages (phone_number, sender, body, code, service) VALUES (?, ?, ?, ?, ?)",
                                               (phone_number, sender, body, code, service))
                                conn.commit()
                                messages.append({"sender": sender, "body": body, "code": code, "service": service})
                except Exception as e:
                    print("Error polling 5SIM status:", e)
                    
    conn.close()
    return {"status": "success", "messages": messages}