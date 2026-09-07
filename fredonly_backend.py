from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from jose import JWTError, jwt
from dotenv import load_dotenv

import datetime
import requests
import uvicorn
import os
import uuid


# ==========================================
# LOAD ENVIRONMENT
# ==========================================

load_dotenv()


# ==========================================
# APP
# ==========================================

app = FastAPI(
    title="Fred OTP API",
    version="2.0.0"
)


# ==========================================
# CORS
# ==========================================

allowed_origins_raw = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000"
)

allowed_origins = [
    origin.strip()
    for origin in allowed_origins_raw.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# DATABASE
# ==========================================

SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./fredonly.db"
)

connect_args = {}

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False
    }

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# ==========================================
# PASSWORD SECURITY
# ==========================================

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto"
)


# ==========================================
# JWT SECURITY
# ==========================================

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY is missing. "
        "Add it to your environment variables."
    )

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256"
)

# ==================================================
# FRED_JWT_HARDENING_V3
# ==================================================

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "1440"
    )
)

JWT_ISSUER = os.getenv(
    "JWT_ISSUER",
    "fred-otp-api"
)

JWT_TOKEN_TYPE = "access"

if len(JWT_SECRET_KEY) < 32:
    raise RuntimeError(
        "JWT_SECRET_KEY must contain at least 32 characters."
    )

security = HTTPBearer(
    auto_error=False
)

# END FRED_JWT_HARDENING_V3


# ==========================================
# EXTERNAL PROVIDERS
# ==========================================

FIVESIM_API_KEY = os.getenv(
    "FIVESIM_API_KEY",
    ""
)

FIVESIM_BASE_URL = os.getenv(
    "FIVESIM_BASE_URL",
    "https://5sim.net/v1"
)


# ==========================================
# SAFETY FLAGS
# ==========================================

ENABLE_TEST_FUNDING = os.getenv(
    "ENABLE_TEST_FUNDING",
    "false"
).lower() == "true"


ALLOW_MOCK_NUMBERS = os.getenv(
    "ALLOW_MOCK_NUMBERS",
    "false"
).lower() == "true"


# ==========================================
# DATABASE MODELS
# ==========================================

class UserWallet(Base):

    __tablename__ = "user_wallets"

    user_id = Column(
        String,
        primary_key=True,
        index=True
    )

    balance_ngn = Column(
        Float,
        default=0.0
    )

    password_hash = Column(
        String,
        nullable=False
    )


class TransactionLedger(Base):

    __tablename__ = "transactions"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True
    )

    user_id = Column(
        String,
        index=True
    )

    type = Column(
        String
    )

    amount = Column(
        "amount_ngn",
        Float
    )

    desc = Column(
        "description",
        String
    )

    timestamp = Column(
        DateTime,
        default=datetime.datetime.utcnow
    )


class RentedNumber(Base):

    __tablename__ = "rented_numbers"

    activation_id = Column(
        String,
        primary_key=True,
        index=True
    )

    user_id = Column(
        String,
        index=True,
        nullable=False
    )

    phone_number = Column(
        String,
        index=True,
        nullable=False
    )

    service_name = Column(
        String,
        nullable=False
    )

    country = Column(
        String,
        default="usa"
    )

    status = Column(
        String,
        default="ACTIVE"
    )

    created_at = Column(
        DateTime,
        default=datetime.datetime.utcnow
    )


# ==========================================
# CREATE TABLES
# IMPORTANT:
# DOES NOT DELETE EXISTING DATABASE
# ==========================================

Base.metadata.create_all(
    bind=engine
)


# ==========================================
# REQUEST MODELS
# ==========================================

class AuthPayload(BaseModel):

    username: str = Field(
        min_length=3,
        max_length=50
    )

    password: str = Field(
        min_length=6,
        max_length=256
    )


class FundPayload(BaseModel):

    amount_ngn: float = Field(
        gt=0,
        le=10000000
    )


class RentPayload(BaseModel):

    service_name: str = Field(
        min_length=1,
        max_length=100
    )

    country: str = Field(
        default="usa",
        min_length=2,
        max_length=50
    )


class CancelPayload(BaseModel):

    activation_id: str = Field(
        min_length=1,
        max_length=200
    )


# ==========================================
# DATABASE DEPENDENCY
# ==========================================

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()


# ==========================================
# JWT FUNCTIONS
# ==========================================

def create_access_token(
    username: str
):
    now = datetime.datetime.utcnow()

    expire = (
        now
        + datetime.timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    payload = {
        "sub": username,
        "iat": now,
        "exp": expire,
        "iss": JWT_ISSUER,
        "jti": str(uuid.uuid4()),
        "typ": JWT_TOKEN_TYPE
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db = Depends(get_db)
):
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )

        username = payload.get("sub")

        if (
            not isinstance(username, str)
            or not username.strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token."
            )

        username = username.strip()

        token_issuer = payload.get("iss")

        if (
            token_issuer is not None
            and token_issuer != JWT_ISSUER
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token."
            )

        token_type = payload.get("typ")

        if (
            token_type is not None
            and token_type != JWT_TOKEN_TYPE
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token."
            )

        token_jti = payload.get("jti")

        if (
            token_issuer is not None
            and (
                not isinstance(token_jti, str)
                or not token_jti.strip()
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token."
            )

        token_iat = payload.get("iat")

        if (
            token_iat is not None
            and not isinstance(token_iat, (int, float))
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token."
            )

    except HTTPException:
        raise

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is invalid or expired."
        )

    user = db.query(
        UserWallet
    ).filter(
        UserWallet.user_id == username
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists."
        )

    return user


# ==========================================
# SERVICE NORMALIZATION
# ==========================================

def normalize_service(
    service_name: str
):

    service_raw = service_name.lower().strip()


    if "telegram" in service_raw:

        return "telegram"


    elif "whatsapp" in service_raw:

        return "whatsapp"


    elif "google" in service_raw:

        return "google"


    elif "gmail" in service_raw:

        return "google"


    elif "facebook" in service_raw:

        return "facebook"


    elif "instagram" in service_raw:

        return "instagram"


    elif "twitter" in service_raw:

        return "twitter"


    elif "x.com" in service_raw:

        return "twitter"


    elif "tinder" in service_raw:

        return "tinder"


    elif "discord" in service_raw:

        return "discord"


    return "other"


# ==========================================
# HEALTH CHECK
# ==========================================

@app.get("/")

def home():

    return {
        "success": True,
        "service": "Fred OTP API",
        "version": "2.0.0",
        "authentication": "JWT enabled"
    }


@app.get("/health")

def health():

    return {
        "status": "healthy"
    }


# ==========================================
# SIGN UP
# ==========================================

@app.post("/api/v1/auth/signup")

def signup(

    payload: AuthPayload,

    db = Depends(get_db)

):

    username = payload.username.strip()


    existing_user = db.query(UserWallet).filter(
        UserWallet.user_id == username
    ).first()


    if existing_user:

        raise HTTPException(
            status_code=409,
            detail=(
                "Username already taken. "
                "Please choose another."
            )
        )


    hashed_password = pwd_context.hash(
        payload.password
    )


    new_user = UserWallet(

        user_id=username,

        balance_ngn=0.0,

        password_hash=hashed_password

    )


    db.add(
        new_user
    )

    db.commit()


    token = create_access_token(
        username
    )


    return {

        "success": True,

        "message":
        "Account created successfully.",

        "username":
        username,

        "access_token":
        token,

        "token_type":
        "bearer"

    }


# ==========================================
# SIGN IN
# ==========================================

@app.post("/api/v1/auth/signin")

def signin(

    payload: AuthPayload,

    db = Depends(get_db)

):

    username = payload.username.strip()


    user = db.query(UserWallet).filter(
        UserWallet.user_id == username
    ).first()


    if (

        not user

        or

        not user.password_hash

        or

        not pwd_context.verify(
            payload.password,
            user.password_hash
        )

    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password."
        )


    token = create_access_token(
        user.user_id
    )


    return {

        "success": True,

        "message":
        "Login successful!",

        "username":
        user.user_id,

        "access_token":
        token,

        "token_type":
        "bearer"

    }


# ==========================================
# CURRENT USER
# ==========================================

@app.get("/api/v1/auth/me")

def get_me(

    current_user: UserWallet = Depends(
        get_current_user
    )

):

    return {

        "username":
        current_user.user_id,

        "balance_ngn":
        current_user.balance_ngn

    }


# ==========================================
# WALLET
# ==========================================

@app.get("/api/v1/wallet/me")

def get_wallet(

    current_user: UserWallet = Depends(
        get_current_user
    ),

    db = Depends(get_db)

):

    transactions = db.query(
        TransactionLedger
    ).filter(

        TransactionLedger.user_id
        ==
        current_user.user_id

    ).order_by(

        TransactionLedger.timestamp.desc()

    ).all()


    transactions_list = []


    for transaction in transactions:

        transactions_list.append({

            "id":
            transaction.id,

            "type":
            transaction.type,

            "amount":
            transaction.amount,

            "desc":
            transaction.desc,

            "timestamp":
            transaction.timestamp.isoformat()
            if transaction.timestamp
            else None

        })


    return {

        "username":
        current_user.user_id,

        "balance_ngn":
        current_user.balance_ngn,

        "transactions":
        transactions_list

    }


# ==========================================
# TEST WALLET FUNDING
#
# IMPORTANT:
# DISABLED BY DEFAULT ON PRODUCTION
#
# USE PAYSTACK WEBHOOK FOR REAL MONEY
# ==========================================

@app.post("/api/v1/wallet/fund")

def fund_wallet(

    payload: FundPayload,

    current_user: UserWallet = Depends(
        get_current_user
    ),

    db = Depends(get_db)

):

    if not ENABLE_TEST_FUNDING:

        raise HTTPException(
            status_code=403,
            detail=(
                "Direct wallet funding is disabled. "
                "Use the verified payment system."
            )
        )


    current_user.balance_ngn += (
        payload.amount_ngn
    )


    transaction = TransactionLedger(

        user_id=current_user.user_id,

        type="CREDIT",

        amount=payload.amount_ngn,

        desc="Test wallet funding"

    )


    db.add(
        transaction
    )

    db.commit()

    db.refresh(
        current_user
    )


    return {

        "success": True,

        "new_balance_ngn":
        current_user.balance_ngn

    }


# ==========================================
# RENT NUMBER
# ==========================================

@app.post("/api/v1/numbers/rent")

def rent_number(

    payload: RentPayload,

    current_user: UserWallet = Depends(
        get_current_user
    ),

    db = Depends(get_db)

):

    cost = 350.0


    if current_user.balance_ngn < cost:

        raise HTTPException(
            status_code=400,
            detail=(
                "Insufficient wallet balance. "
                "Please top up."
            )
        )


    service_slug = normalize_service(
        payload.service_name
    )


    phone = None

    activation_id = None


    country = (
        payload.country
        .lower()
        .strip()
    )


    if FIVESIM_API_KEY:

        headers = {

            "Authorization":
            f"Bearer {FIVESIM_API_KEY}",

            "Accept":
            "application/json"

        }


        try:

            response = requests.get(

                f"{FIVESIM_BASE_URL}/user/buy/activation/{country}/any/{service_slug}",

                headers=headers,

                timeout=20

            )


            if response.status_code == 200:

                provider_data = response.json()

                phone = provider_data.get(
                    "phone"
                )

                activation_id = str(
                    provider_data.get(
                        "id"
                    )
                )


            else:

                raise HTTPException(

                    status_code=502,

                    detail=(
                        "Number provider could not complete "
                        "the request."
                    )

                )


        except HTTPException:

            raise


        except Exception:

            raise HTTPException(

                status_code=502,

                detail=(
                    "Could not contact number provider."
                )

            )


    elif ALLOW_MOCK_NUMBERS:

        phone = "+12055550199"

        activation_id = (
            "mock_"
            +
            str(
                uuid.uuid4()
            )
        )


    else:

        raise HTTPException(

            status_code=503,

            detail=(
                "Number provider is not configured."
            )

        )


    if not phone or not activation_id:

        raise HTTPException(

            status_code=502,

            detail=(
                "Provider returned invalid number data."
            )

        )


    current_user.balance_ngn -= cost


    transaction = TransactionLedger(

        user_id=current_user.user_id,

        type="DEBIT",

        amount=cost,

        desc=(
            "Rented virtual number for "
            +
            payload.service_name
        )

    )


    rented_number = RentedNumber(

        activation_id=activation_id,

        user_id=current_user.user_id,

        phone_number=phone,

        service_name=payload.service_name,

        country=country,

        status="ACTIVE"

    )


    db.add(
        transaction
    )

    db.add(
        rented_number
    )

    db.commit()


    return {

        "success": True,

        "phone_number":
        phone,

        "service":
        payload.service_name,

        "activation_id":
        activation_id,

        "country":
        country,

        "cost":
        cost

    }


# ==========================================
# MY NUMBERS
# ==========================================

@app.get("/api/v1/numbers/me")

def get_my_numbers(

    current_user: UserWallet = Depends(
        get_current_user
    ),

    db = Depends(get_db)

):

    numbers = db.query(
        RentedNumber
    ).filter(

        RentedNumber.user_id
        ==
        current_user.user_id

    ).order_by(

        RentedNumber.created_at.desc()

    ).all()


    results = []


    for number in numbers:

        results.append({

            "activation_id":
            number.activation_id,

            "phone_number":
            number.phone_number,

            "service_name":
            number.service_name,

            "country":
            number.country,

            "status":
            number.status,

            "created_at":
            number.created_at.isoformat()
            if number.created_at
            else None

        })


    return {

        "numbers":
        results

    }


# ==========================================
# SMS INBOX
#
# USER MUST OWN THE NUMBER
# ==========================================

@app.get("/api/v1/sms/inbox/{phone_number}")

def get_inbox(

    phone_number: str,

    current_user: UserWallet = Depends(
        get_current_user
    ),

    db = Depends(get_db)

):

    rented_number = db.query(
        RentedNumber
    ).filter(

        RentedNumber.phone_number
        ==
        phone_number,

        RentedNumber.user_id
        ==
        current_user.user_id

    ).first()


    if not rented_number:

        raise HTTPException(

            status_code=404,

            detail=(
                "Number not found or does not belong "
                "to your account."
            )

        )


    if rented_number.status != "ACTIVE":

        raise HTTPException(

            status_code=400,

            detail="This number is no longer active."

        )


    messages = []


    # ======================================
    # MOCK SMS MODE
    # ======================================

    if rented_number.activation_id.startswith(
        "mock_"
    ):

        messages = [

            {

                "sender":
                "VerificationBot",

                "body":
                "Your security code is 782910.",

                "code":
                "782910",

                "service":
                rented_number.service_name

            }

        ]


    # ======================================
    # REAL PROVIDER SMS
    # ======================================

    elif FIVESIM_API_KEY:

        headers = {

            "Authorization":
            f"Bearer {FIVESIM_API_KEY}",

            "Accept":
            "application/json"

        }


        try:

            response = requests.get(

                f"{FIVESIM_BASE_URL}/user/check/{rented_number.activation_id}",

                headers=headers,

                timeout=20

            )


            if response.status_code == 200:

                provider_data = response.json()

                sms_list = provider_data.get(
                    "sms",
                    []
                )


                for sms in sms_list:

                    messages.append({

                        "sender":
                        sms.get(
                            "sender",
                            "Unknown"
                        ),

                        "body":
                        sms.get(
                            "text",
                            ""
                        ),

                        "code":
                        sms.get(
                            "code",
                            ""
                        ),

                        "service":
                        rented_number.service_name

                    })


        except Exception:

            raise HTTPException(

                status_code=502,

                detail=(
                    "Could not retrieve SMS from provider."
                )

            )


    return {

        "phone_number":
        phone_number,

        "messages":
        messages

    }


# ==========================================
# CANCEL NUMBER
#
# USER MUST OWN THE NUMBER
# ==========================================

@app.post("/api/v1/numbers/cancel")

def cancel_number(

    payload: CancelPayload,

    current_user: UserWallet = Depends(
        get_current_user
    ),

    db = Depends(get_db)

):

    rented_number = db.query(
        RentedNumber
    ).filter(

        RentedNumber.activation_id
        ==
        payload.activation_id,

        RentedNumber.user_id
        ==
        current_user.user_id

    ).first()


    if not rented_number:

        raise HTTPException(

            status_code=404,

            detail=(
                "Number not found or does not belong "
                "to your account."
            )

        )


    if rented_number.status != "ACTIVE":

        raise HTTPException(

            status_code=400,

            detail="Number is already inactive."

        )


    rented_number.status = "CANCELLED"


    refund_amount = 350.0


    current_user.balance_ngn += (
        refund_amount
    )


    transaction = TransactionLedger(

        user_id=current_user.user_id,

        type="CREDIT",

        amount=refund_amount,

        desc=(
            "Refund for cancelled virtual number "
            +
            rented_number.phone_number
        )

    )


    db.add(
        transaction
    )

    db.commit()


    return {

        "success": True,

        "message":
        "Number cancelled and refund processed.",

        "refund_ngn":
        refund_amount

    }


# ==========================================
# SERVER STATUS
# ==========================================

@app.get("/api/v1/status")

def api_status():

    return {

        "success": True,

        "api":
        "Fred OTP API",

        "version":
        "2.0.0",

        "authentication":
        "JWT",

        "provider_configured":
        bool(FIVESIM_API_KEY),

        "test_funding_enabled":
        ENABLE_TEST_FUNDING

    }
# ==========================================
# SERVER STARTUP
# ==========================================
#
# Allows:
#     python fredonly_backend.py
#
# to actually start the FastAPI server.
# ==========================================


# ==================================================
# FRED_WALLET_HISTORY_ENDPOINT_V1
# ==================================================

@app.get("/api/v1/wallet/history")
def get_wallet_history(
    limit: int = 50,
    current_user: UserWallet = Depends(
        get_current_user
    ),
    db = Depends(get_db)
):
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 50

    transactions = db.query(
        TransactionLedger
    ).filter(
        TransactionLedger.user_id
        ==
        current_user.user_id
    ).order_by(
        TransactionLedger.timestamp.desc()
    ).limit(
        limit
    ).all()

    results = []

    for transaction in transactions:

        results.append({
            "id":
                transaction.id,

            "type":
                transaction.type,

            "amount_ngn":
                float(transaction.amount or 0),

            "description":
                transaction.desc
                or "",

            "timestamp":
                transaction.timestamp.isoformat()
                if transaction.timestamp
                else None
        })

    return {
        "transactions": results,
        "count": len(results)
    }

# END FRED_WALLET_HISTORY_ENDPOINT_V1

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5000
    )



