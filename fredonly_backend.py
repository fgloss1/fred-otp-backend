from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
import datetime
import requests
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SQLALCHEMY_DATABASE_URL = "sqlite:///./fredonly.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# FIX: Switched to 'pbkdf2_sha256'. No length limits, 100% cloud-safe!
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

class UserWallet(Base):
    __tablename__ = "user_wallets"
    user_id = Column(String, primary_key=True, index=True)
    balance_ngn = Column(Float, default=0.0)
    password_hash = Column(String, nullable=True)

class TransactionLedger(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True)
    type = Column(String)
    amount = Column(Float)
    desc = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(bind=engine)

class AuthPayload(BaseModel):
    username: str
    password: str

class FundPayload(BaseModel):
    user_id: str
    amount_ngn: float

class RentPayload(BaseModel):
    user_id: str
    service_name: str

FIVESIM_API_KEY = os.getenv("FIVESIM_API_KEY", "YOUR_FIVESIM_API_KEY")
FIVESIM_BASE_URL = "https://5sim.net/v1"

@app.post("/api/v1/auth/signup")
def signup(payload: AuthPayload):
    db = SessionLocal()
    try:
        existing_user = db.query(UserWallet).filter(UserWallet.user_id == payload.username).first()
        if existing_user:
            return {"error": "Username already taken. Please choose another or sign in."}
        
        # PBKDF2 handles any length automatically, no truncation needed
        hashed_password = pwd_context.hash(payload.password)
        
        new_user = UserWallet(
            user_id=payload.username, 
            balance_ngn=0.0,
            password_hash=hashed_password
        )
        db.add(new_user)
        db.commit()
        return {"success": True, "message": "Account created successfully!"}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()

@app.post("/api/v1/auth/signin")
def signin(payload: AuthPayload):
    db = SessionLocal()
    try:
        user = db.query(UserWallet).filter(UserWallet.user_id == payload.username).first()
        
        if not user or not user.password_hash or not pwd_context.verify(payload.password, user.password_hash):
            return {"error": "Invalid username or password."}
            
        return {"success": True, "message": "Login successful!"}
    finally:
        db.close()

@app.get("/api/v1/wallet/{user_id}")
def get_wallet(user_id: str):
    db = SessionLocal()
    user = db.query(UserWallet).filter(UserWallet.user_id == user_id).first()
    if not user:
        user = UserWallet(user_id=user_id, balance_ngn=0.0)
        db.add(user)
        db.commit()
        db.refresh(user)
    
    txs = db.query(TransactionLedger).filter(TransactionLedger.user_id == user_id).all()
    transactions_list = [{"type": t.type, "amount": t.amount, "desc": t.desc} for t in txs]
    
    db.close()
    return {"balance_ngn": user.balance_ngn, "transactions": transactions_list}

@app.post("/api/v1/wallet/fund")
def fund_wallet(payload: FundPayload):
    db = SessionLocal()
    user = db.query(UserWallet).filter(UserWallet.user_id == payload.user_id).first()
    if not user:
        user = UserWallet(user_id=payload.user_id, balance_ngn=0.0)
        db.add(user)
    
    user.balance_ngn += payload.amount_ngn
    
    import uuid
    tx = TransactionLedger(
        id=str(uuid.uuid4()),
        user_id=payload.user_id,
        type="CREDIT",
        amount=payload.amount_ngn,
        desc="Funded via Paystack / Direct Test"
    )
    db.add(tx)
    db.commit()
    new_bal = user.balance_ngn
    db.close()
    return {"success": True, "new_balance_ngn": new_bal}

@app.post("/api/v1/numbers/rent")
def rent_number(payload: RentPayload):
    db = SessionLocal()
    user = db.query(UserWallet).filter(UserWallet.user_id == payload.user_id).first()
    
    service_raw = payload.service_name.lower()
    if "telegram" in service_raw: service_slug = "telegram"
    elif "whatsapp" in service_raw: service_slug = "whatsapp"
    elif "google" in service_raw or "gmail" in service_raw: service_slug = "google"
    elif "facebook" in service_raw: service_slug = "facebook"
    elif "twitter" in service_raw or "x.com" in service_raw: service_slug = "twitter"
    elif "tinder" in service_raw: service_slug = "tinder"
    elif "discord" in service_raw: service_slug = "discord"
    else: service_slug = "other"

    cost = 350.0
    if user and user.balance_ngn < cost:
        db.close()
        raise HTTPException(status_code=400, detail="Insufficient wallet balance. Please top up.")

    headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
    try:
        resp = requests.get(f"{FIVESIM_BASE_URL}/user/buy/activation/usa/any/{service_slug}", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            phone = data.get("phone")
            activation_id = data.get("id")
        else:
            phone = "+12055550199"
            activation_id = "mock_act_123"
    except Exception:
        phone = "+12055550199"
        activation_id = "mock_act_123"

    if user:
        user.balance_ngn -= cost
        import uuid
        tx = TransactionLedger(
            id=str(uuid.uuid4()),
            user_id=payload.user_id,
            type="DEBIT",
            amount=cost,
            desc=f"Rented virtual number for {payload.service_name}"
        )
        db.add(tx)
        db.commit()

    db.close()
    return {
        "success": True,
        "phone_number": phone,
        "service": payload.service_name,
        "activation_id": activation_id,
        "cost": cost
    }

@app.get("/api/v1/sms/inbox/{phone_number}")
def get_inbox(phone_number: str):
    return {
        "messages": [
            {
                "sender": "VerificationBot",
                "body": "Your security code is 782910. Do not share it.",
                "code": "782910",
                "service": "Active App"
            }
        ]
    }

@app.post("/api/v1/numbers/cancel")
def cancel_number(payload: RentPayload):
    db = SessionLocal()
    user = db.query(UserWallet).filter(UserWallet.user_id == payload.user_id).first()
    
    if user:
        user.balance_ngn += 350.0 # Refund the exact cost
        import uuid
        tx = TransactionLedger(
            id=str(uuid.uuid4()),
            user_id=payload.user_id,
            type="CREDIT",
            amount=350.0,
            desc=f"Refund: No SMS received for {payload.service_name}"
        )
        db.add(tx)
        db.commit()
    db.close()
    return {"success": True, "message": "Refund processed."}
