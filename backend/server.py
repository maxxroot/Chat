from fastapi import FastAPI, APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import json
import time
import hashlib
import hmac
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import canonicaljson
from signedjson import key, sign
import httpx
from passlib.context import CryptContext
from jose import JWTError, jwt
import bcrypt

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Database setup
MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
SERVER_NAME = os.environ['SERVER_NAME']
SIGNING_KEY_SEED = os.environ['SIGNING_KEY_SEED']

# Authentication settings
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Matrix ID utilities
class MatrixID:
    @staticmethod
    def user_id(localpart: str, server_name: str = None) -> str:
        server = server_name or SERVER_NAME
        return f"@{localpart}:{server}"
    
    @staticmethod
    def room_id(server_name: str = None) -> str:
        server = server_name or SERVER_NAME
        room_localpart = str(uuid.uuid4()).replace('-', '')[:18]
        return f"!{room_localpart}:{server}"
    
    @staticmethod
    def event_id(server_name: str = None) -> str:
        server = server_name or SERVER_NAME
        event_localpart = str(uuid.uuid4()).replace('-', '')[:43]
        return f"${event_localpart}:{server}"

# Pydantic Models for API
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mxid: str  # @user:domain.tld
    localpart: str
    server_name: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    password_hash: Optional[str] = None
    is_active: bool = True
    public_key: Optional[str] = None  # RSA public key for E2E encryption
    private_key: Optional[str] = None  # RSA private key (encrypted with user password)
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Authentication Models
class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    display_name: Optional[str] = None

class UserLoginRequest(BaseModel):
    username: str
    password: str

class UserProfile(BaseModel):
    mxid: str
    localpart: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None
    is_active: bool
    created_at: datetime

class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: UserProfile

class TokenData(BaseModel):
    username: Optional[str] = None

class Room(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    room_id: str  # !room:domain.tld
    name: Optional[str] = None
    topic: Optional[str] = None
    avatar_url: Optional[str] = None
    is_public: bool = True
    creator_mxid: str
    version: str = "1"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class RoomMember(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    room_id: str
    user_mxid: str
    membership: str = "join"  # join, leave, invite, ban
    power_level: int = 0
    joined_at: datetime = Field(default_factory=datetime.utcnow)

class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    room_id: str
    sender: str
    event_type: str  # m.room.message, m.room.member, etc.
    content: Dict[str, Any]
    state_key: Optional[str] = None
    origin_server_ts: datetime = Field(default_factory=datetime.utcnow)
    signatures: Optional[Dict[str, Dict[str, str]]] = None

class ServerKey(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    server_name: str
    key_id: str
    verify_key: str
    valid_until_ts: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# API Request Models
class MatrixEvent(BaseModel):
    event_id: str
    room_id: str
    sender: str
    type: str
    content: Dict[str, Any]
    state_key: Optional[str] = None
    origin_server_ts: int
    signatures: Dict[str, Dict[str, str]]

class CreateRoomRequest(BaseModel):
    name: Optional[str] = None
    topic: Optional[str] = None
    preset: str = "public_chat"

class JoinRoomRequest(BaseModel):
    room_id: str

class SendMessageRequest(BaseModel):
    msgtype: str = "m.text"
    body: str

# New models for contacts and private messaging
class Contact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_mxid: str  # The user who owns this contact
    contact_mxid: str  # The contact's Matrix ID
    contact_display_name: Optional[str] = None
    contact_avatar_url: Optional[str] = None
    contact_public_key: Optional[str] = None  # Contact's public key for E2E
    status: str = "active"  # active, blocked
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PrivateMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str  # Unique message ID
    sender_mxid: str
    recipient_mxid: str
    encrypted_content: str  # AES encrypted message content
    encrypted_aes_key_sender: str  # AES key encrypted with sender's RSA public key
    encrypted_aes_key_recipient: str  # AES key encrypted with recipient's RSA public key
    iv: str  # Initialization vector for AES
    auth_tag: str  # Authentication tag for AES-GCM
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ContactSearchRequest(BaseModel):
    query: str  # Username or Matrix ID to search for

class AddContactRequest(BaseModel):
    contact_mxid: str  # Matrix ID of user to add as contact

class SendPrivateMessageRequest(BaseModel):
    recipient_mxid: str
    message: str

# Crypto utilities for Matrix federation
class MatrixSigning:
    def __init__(self):
        # Generate server signing key from seed
        seed = SIGNING_KEY_SEED.encode()[:32].ljust(32, b'\0')
        self.signing_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        self.verify_key = self.signing_key.public_key()
    
    def get_verify_key_base64(self) -> str:
        public_bytes = self.verify_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return base64.b64encode(public_bytes).decode()
    
    def sign_json(self, json_object: Dict[str, Any]) -> Dict[str, Any]:
        signed = dict(json_object)
        
        # Convert datetime objects to timestamps for JSON serialization
        def convert_datetimes(obj):
            if isinstance(obj, dict):
                return {k: convert_datetimes(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetimes(item) for item in obj]
            elif isinstance(obj, datetime):
                return int(obj.timestamp() * 1000)  # Convert to milliseconds timestamp
            else:
                return obj
        
        signed_converted = convert_datetimes(signed)
        canonical = canonicaljson.encode_canonical_json(signed_converted)
        signature = self.signing_key.sign(canonical)
        signature_base64 = base64.b64encode(signature).decode()
        
        # Initialize signatures if not present
        if "signatures" not in signed:
            signed["signatures"] = {}
        if signed["signatures"] is None:
            signed["signatures"] = {}
        if SERVER_NAME not in signed["signatures"]:
            signed["signatures"][SERVER_NAME] = {}
        
        signed["signatures"][SERVER_NAME][f"ed25519:key1"] = signature_base64
        return signed

# Initialize signing
matrix_signing = MatrixSigning()

# E2E Encryption utilities
class E2EEncryption:
    @staticmethod
    def generate_rsa_keys():
        """Generate RSA key pair for a user"""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        public_key = private_key.public_key()
        
        # Serialize keys to PEM format
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        return private_pem.decode(), public_pem.decode()
    
    @staticmethod
    def encrypt_message(message: str, recipient_public_key_pem: str) -> dict:
        """Encrypt a message using hybrid RSA+AES encryption"""
        # Generate random AES key and IV
        aes_key = os.urandom(32)  # 256-bit key
        iv = os.urandom(12)  # 96-bit nonce for GCM
        
        # Load recipient's public key
        recipient_public_key = serialization.load_pem_public_key(
            recipient_public_key_pem.encode(),
            backend=default_backend()
        )
        
        # Encrypt AES key with recipient's RSA public key
        encrypted_aes_key = recipient_public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        # Encrypt message with AES-GCM
        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(message.encode()) + encryptor.finalize()
        auth_tag = encryptor.tag
        
        return {
            'encrypted_content': base64.b64encode(ciphertext).decode(),
            'encrypted_aes_key': base64.b64encode(encrypted_aes_key).decode(),
            'iv': base64.b64encode(iv).decode(),
            'auth_tag': base64.b64encode(auth_tag).decode()
        }
    
    @staticmethod
    def decrypt_message(encrypted_content: str, encrypted_aes_key: str, 
                       iv: str, auth_tag: str, private_key_pem: str) -> str:
        """Decrypt a message using hybrid RSA+AES decryption"""
        # Load private key
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=None,
            backend=default_backend()
        )
        
        # Decrypt AES key with RSA private key
        aes_key = private_key.decrypt(
            base64.b64decode(encrypted_aes_key),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        # Decrypt message with AES-GCM
        cipher = Cipher(
            algorithms.AES(aes_key), 
            modes.GCM(base64.b64decode(iv), base64.b64decode(auth_tag)), 
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(base64.b64decode(encrypted_content)) + decryptor.finalize()
        
        return decrypted.decode()

# Initialize E2E encryption
e2e_crypto = E2EEncryption()

# Authentication utilities
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_user_by_username(username: str) -> Optional[Dict]:
    """Get user by username from database"""
    user = await db.users.find_one({"localpart": username})
    return user

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    user = await get_user_by_username(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: dict = Depends(get_current_user)):
    """Get current active user"""
    if not current_user.get("is_active", True):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        # Dictionary to store active connections by room_id
        self.room_connections: Dict[str, List[WebSocket]] = {}
        
    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        if room_id not in self.room_connections:
            self.room_connections[room_id] = []
        self.room_connections[room_id].append(websocket)
        logger.info(f"WebSocket connected to room {room_id}. Total connections: {len(self.room_connections[room_id])}")
        
    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.room_connections:
            self.room_connections[room_id].remove(websocket)
            if len(self.room_connections[room_id]) == 0:
                del self.room_connections[room_id]
        logger.info(f"WebSocket disconnected from room {room_id}")
        
    async def broadcast_to_room(self, room_id: str, message: dict):
        if room_id in self.room_connections:
            disconnected_websockets = []
            for websocket in self.room_connections[room_id]:
                try:
                    await websocket.send_json(message)
                except:
                    disconnected_websockets.append(websocket)
            
            # Remove disconnected websockets
            for websocket in disconnected_websockets:
                self.disconnect(websocket, room_id)

# Initialize connection manager
manager = ConnectionManager()

# Create the main app
app = FastAPI(title="LibraChat Federation Server")
api_router = APIRouter(prefix="/api")

# Authentication endpoints
@api_router.post("/auth/register", response_model=Token)
async def register_user(user_data: UserRegisterRequest):
    """Register a new user"""
    # Check if user already exists
    existing_user = await db.users.find_one({
        "$or": [
            {"localpart": user_data.username},
            {"email": user_data.email}
        ]
    })
    
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username or email already registered"
        )
    
    # Generate RSA keys for E2E encryption
    private_key_pem, public_key_pem = e2e_crypto.generate_rsa_keys()
    
    # Create new user
    user_id = str(uuid.uuid4())
    mxid = MatrixID.user_id(user_data.username)
    password_hash = get_password_hash(user_data.password)
    
    user_doc = {
        "id": user_id,
        "mxid": mxid,
        "localpart": user_data.username,
        "server_name": SERVER_NAME,
        "email": user_data.email,
        "display_name": user_data.display_name or user_data.username,
        "avatar_url": None,
        "password_hash": password_hash,
        "is_active": True,
        "public_key": public_key_pem,
        "private_key": private_key_pem,  # In production, this should be encrypted with user's password
        "created_at": datetime.utcnow()
    }
    
    await db.users.insert_one(user_doc)
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_data.username}, expires_delta=access_token_expires
    )
    
    user_profile = UserProfile(
        mxid=mxid,
        localpart=user_data.username,
        display_name=user_doc["display_name"],
        avatar_url=user_doc["avatar_url"],
        email=user_data.email,
        is_active=True,
        created_at=user_doc["created_at"]
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_profile
    )

@api_router.post("/auth/login", response_model=Token)
async def login_user(form_data: UserLoginRequest):
    """Authenticate user and return token"""
    user = await get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["localpart"]}, expires_delta=access_token_expires
    )
    
    user_profile = UserProfile(
        mxid=user["mxid"],
        localpart=user["localpart"],
        display_name=user.get("display_name"),
        avatar_url=user.get("avatar_url"),
        email=user.get("email"),
        is_active=user.get("is_active", True),
        created_at=user["created_at"]
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_profile
    )

@api_router.get("/auth/me", response_model=UserProfile)
async def get_current_user_profile(current_user: dict = Depends(get_current_active_user)):
    """Get current user profile"""
    return UserProfile(
        mxid=current_user["mxid"],
        localpart=current_user["localpart"],
        display_name=current_user.get("display_name"),
        avatar_url=current_user.get("avatar_url"),
        email=current_user.get("email"),
        is_active=current_user.get("is_active", True),
        created_at=current_user["created_at"]
    )

# ===== CONTACTS AND PRIVATE MESSAGING ENDPOINTS =====

@api_router.post("/contacts/search")
async def search_users(search_request: ContactSearchRequest, current_user: dict = Depends(get_current_active_user)):
    """Search for users locally and from federated instances"""
    query = search_request.query.strip()
    if not query:
        return {"users": []}
    
    users = []
    
    # Check if query looks like a Matrix ID (contains @)
    if "@" in query and ":" in query:
        # Search for federated user by Matrix ID
        # For now, we'll just check our local database for any cached federated users
        # In a full implementation, you'd query the federated server
        federated_user = await db.users.find_one({"mxid": query})
        if federated_user and federated_user["mxid"] != current_user["mxid"]:
            users.append({
                "mxid": federated_user["mxid"],
                "localpart": federated_user["localpart"],
                "server_name": federated_user["server_name"],
                "display_name": federated_user.get("display_name"),
                "avatar_url": federated_user.get("avatar_url"),
                "is_federated": federated_user["server_name"] != SERVER_NAME
            })
    else:
        # Search local users by localpart (username)
        local_users_cursor = db.users.find({
            "localpart": {"$regex": query, "$options": "i"},
            "server_name": SERVER_NAME,
            "mxid": {"$ne": current_user["mxid"]}  # Exclude current user
        }).limit(20)
        
        async for user in local_users_cursor:
            users.append({
                "mxid": user["mxid"],
                "localpart": user["localpart"],
                "server_name": user["server_name"],
                "display_name": user.get("display_name"),
                "avatar_url": user.get("avatar_url"),
                "is_federated": False
            })
    
    return {"users": users}

@api_router.post("/contacts/add")
async def add_contact(add_request: AddContactRequest, current_user: dict = Depends(get_current_active_user)):
    """Add a user as a contact"""
    contact_mxid = add_request.contact_mxid
    user_mxid = current_user["mxid"]
    
    if contact_mxid == user_mxid:
        raise HTTPException(status_code=400, detail="Cannot add yourself as a contact")
    
    # Check if contact already exists
    existing_contact = await db.contacts.find_one({
        "user_mxid": user_mxid,
        "contact_mxid": contact_mxid
    })
    
    if existing_contact:
        raise HTTPException(status_code=400, detail="Contact already exists")
    
    # Get contact user info
    contact_user = await db.users.find_one({"mxid": contact_mxid})
    if not contact_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Create contact record
    contact_doc = {
        "id": str(uuid.uuid4()),
        "user_mxid": user_mxid,
        "contact_mxid": contact_mxid,
        "contact_display_name": contact_user.get("display_name"),
        "contact_avatar_url": contact_user.get("avatar_url"),
        "contact_public_key": contact_user.get("public_key"),
        "status": "active",
        "created_at": datetime.utcnow()
    }
    
    await db.contacts.insert_one(contact_doc)
    
    return {"success": True, "message": "Contact added successfully"}

@api_router.get("/contacts")
async def get_contacts(current_user: dict = Depends(get_current_active_user)):
    """Get user's contacts list"""
    user_mxid = current_user["mxid"]
    
    contacts_cursor = db.contacts.find({
        "user_mxid": user_mxid,
        "status": "active"
    })
    
    contacts = []
    async for contact in contacts_cursor:
        contacts.append({
            "contact_mxid": contact["contact_mxid"],
            "display_name": contact.get("contact_display_name"),
            "avatar_url": contact.get("contact_avatar_url"),
            "created_at": contact["created_at"].isoformat()
        })
    
    return {"contacts": contacts}

@api_router.delete("/contacts/{contact_mxid}")
async def remove_contact(contact_mxid: str, current_user: dict = Depends(get_current_active_user)):
    """Remove a contact"""
    user_mxid = current_user["mxid"]
    
    result = await db.contacts.delete_one({
        "user_mxid": user_mxid,
        "contact_mxid": contact_mxid
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    return {"success": True, "message": "Contact removed successfully"}

@api_router.post("/messages/private/send")
async def send_private_message(message_request: SendPrivateMessageRequest, current_user: dict = Depends(get_current_active_user)):
    """Send an encrypted private message to a contact"""
    sender_mxid = current_user["mxid"]
    recipient_mxid = message_request.recipient_mxid
    message = message_request.message
    
    # Verify contact exists
    contact = await db.contacts.find_one({
        "user_mxid": sender_mxid,
        "contact_mxid": recipient_mxid,
        "status": "active"
    })
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Get recipient's public key
    recipient_user = await db.users.find_one({"mxid": recipient_mxid})
    if not recipient_user or not recipient_user.get("public_key"):
        raise HTTPException(status_code=400, detail="Recipient's encryption key not available")
    
    # Get sender's public key
    sender_public_key = current_user.get("public_key")
    if not sender_public_key:
        raise HTTPException(status_code=400, detail="Sender's encryption key not available")
    
    # Encrypt message for recipient
    encrypted_data_recipient = e2e_crypto.encrypt_message(message, recipient_user["public_key"])
    
    # Encrypt message for sender (so they can see their own messages)
    encrypted_data_sender = e2e_crypto.encrypt_message(message, sender_public_key)
    
    # Create private message record
    message_id = str(uuid.uuid4())
    private_message_doc = {
        "id": str(uuid.uuid4()),
        "message_id": message_id,
        "sender_mxid": sender_mxid,
        "recipient_mxid": recipient_mxid,
        "encrypted_content": encrypted_data_recipient["encrypted_content"],
        "encrypted_aes_key_sender": encrypted_data_sender["encrypted_aes_key"],
        "encrypted_aes_key_recipient": encrypted_data_recipient["encrypted_aes_key"],
        "iv": encrypted_data_recipient["iv"],
        "auth_tag": encrypted_data_recipient["auth_tag"],
        "timestamp": datetime.utcnow()
    }
    
    await db.private_messages.insert_one(private_message_doc)
    
    return {
        "success": True,
        "message_id": message_id,
        "timestamp": private_message_doc["timestamp"].isoformat()
    }

@api_router.get("/messages/private/{contact_mxid}")
async def get_private_messages(contact_mxid: str, limit: int = 50, current_user: dict = Depends(get_current_active_user)):
    """Get decrypted private messages with a contact"""
    user_mxid = current_user["mxid"]
    
    # Verify contact exists
    contact = await db.contacts.find_one({
        "user_mxid": user_mxid,
        "contact_mxid": contact_mxid,
        "status": "active"
    })
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Get current user's private key for decryption
    user_private_key = current_user.get("private_key")
    if not user_private_key:
        raise HTTPException(status_code=400, detail="Decryption key not available")
    
    # Get messages between user and contact
    messages_cursor = db.private_messages.find({
        "$or": [
            {"sender_mxid": user_mxid, "recipient_mxid": contact_mxid},
            {"sender_mxid": contact_mxid, "recipient_mxid": user_mxid}
        ]
    }).sort("timestamp", -1).limit(limit)
    
    messages = []
    async for msg in messages_cursor:
        try:
            # Determine which encrypted key to use
            if msg["sender_mxid"] == user_mxid:
                encrypted_aes_key = msg["encrypted_aes_key_sender"]
            else:
                encrypted_aes_key = msg["encrypted_aes_key_recipient"]
            
            # Decrypt message
            decrypted_content = e2e_crypto.decrypt_message(
                msg["encrypted_content"],
                encrypted_aes_key,
                msg["iv"],
                msg["auth_tag"],
                user_private_key
            )
            
            messages.append({
                "message_id": msg["message_id"],
                "sender_mxid": msg["sender_mxid"],
                "recipient_mxid": msg["recipient_mxid"],
                "content": decrypted_content,
                "timestamp": msg["timestamp"].isoformat(),
                "is_own_message": msg["sender_mxid"] == user_mxid
            })
        except Exception as e:
            logger.warning(f"Failed to decrypt message {msg['message_id']}: {e}")
            # Skip corrupted messages
            continue
    
    # Reverse to get chronological order
    messages.reverse()
    
    return {
        "messages": messages,
        "contact_mxid": contact_mxid
    }

@api_router.get("/conversations")
async def get_conversations(current_user: dict = Depends(get_current_active_user)):
    """Get list of conversations (contacts with recent messages)"""
    user_mxid = current_user["mxid"]
    
    # Get all contacts
    contacts_cursor = db.contacts.find({
        "user_mxid": user_mxid,
        "status": "active"
    })
    
    conversations = []
    async for contact in contacts_cursor:
        contact_mxid = contact["contact_mxid"]
        
        # Get last message with this contact
        last_message = await db.private_messages.find_one({
            "$or": [
                {"sender_mxid": user_mxid, "recipient_mxid": contact_mxid},
                {"sender_mxid": contact_mxid, "recipient_mxid": user_mxid}
            ]
        }, sort=[("timestamp", -1)])
        
        conversations.append({
            "contact_mxid": contact_mxid,
            "display_name": contact.get("contact_display_name"),
            "avatar_url": contact.get("contact_avatar_url"),
            "last_message_timestamp": last_message["timestamp"].isoformat() if last_message else None,
            "has_messages": last_message is not None
        })
    
    # Sort by last message timestamp (most recent first)
    conversations.sort(key=lambda x: x["last_message_timestamp"] or "1970-01-01", reverse=True)
    
    return {"conversations": conversations}

@api_router.put("/auth/me", response_model=UserProfile)
async def update_user_profile(
    update_data: UserUpdateRequest,
    current_user: dict = Depends(get_current_active_user)
):
    """Update current user profile"""
    update_dict = {}
    if update_data.display_name is not None:
        update_dict["display_name"] = update_data.display_name
    if update_data.avatar_url is not None:
        update_dict["avatar_url"] = update_data.avatar_url
    
    if update_dict:
        await db.users.update_one(
            {"localpart": current_user["localpart"]},
            {"$set": update_dict}
        )
        current_user.update(update_dict)
    
    return UserProfile(
        mxid=current_user["mxid"],
        localpart=current_user["localpart"],
        display_name=current_user.get("display_name"),
        avatar_url=current_user.get("avatar_url"),
        email=current_user.get("email"),
        is_active=current_user.get("is_active", True),
        created_at=current_user["created_at"]
    )

# Matrix Federation Discovery Endpoints
@app.get("/.well-known/matrix/server")
async def matrix_server_discovery():
    """Matrix server discovery endpoint"""
    return {"m.server": SERVER_NAME}

@app.get("/.well-known/matrix/client") 
async def matrix_client_discovery():
    """Matrix client discovery endpoint"""
    return {
        "m.homeserver": {
            "base_url": f"https://{SERVER_NAME}"
        }
    }

# Server Key endpoints for federation
@app.get("/_matrix/key/v2/server")
async def get_server_keys():
    """Get server's public keys for federation"""
    valid_until = int((datetime.now(timezone.utc).timestamp() + 86400) * 1000)  # 24h validity
    
    keys = {
        "server_name": SERVER_NAME,
        "verify_keys": {
            "ed25519:key1": {
                "key": matrix_signing.get_verify_key_base64()
            }
        },
        "valid_until_ts": valid_until
    }
    
    # Sign the key response
    signed_keys = matrix_signing.sign_json(keys)
    return signed_keys

# WebSocket endpoint for real-time chat
@api_router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(websocket, room_id)
    try:
        while True:
            # Keep the connection alive and listen for any data
            data = await websocket.receive_text()
            # We can handle ping/pong or other client messages here if needed
            logger.info(f"Received WebSocket data in room {room_id}: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        logger.info(f"WebSocket disconnected from room {room_id}")

# Room Creation and Management
@api_router.post("/createRoom")
async def create_room(request: CreateRoomRequest, current_user: dict = Depends(get_current_active_user)):
    """Create a new Matrix room"""
    room_id = MatrixID.room_id()
    creator_mxid = current_user["mxid"]
    
    # Create room document
    room_data = Room(
        room_id=room_id,
        name=request.name,
        topic=request.topic,
        creator_mxid=creator_mxid,
        is_public=request.preset == "public_chat"
    )
    
    # Insert room into MongoDB
    result = await db.rooms.insert_one(room_data.dict())
    
    # Create room creation event
    event_dict = {
        "event_id": MatrixID.event_id(),
        "room_id": room_id,
        "sender": creator_mxid,
        "type": "m.room.create",
        "content": {
            "creator": creator_mxid,
            "room_version": "1"
        },
        "origin_server_ts": int(time.time() * 1000)
    }
    
    # Sign and store the event
    signed_event_dict = matrix_signing.sign_json(event_dict)
    
    # Create Event object for MongoDB storage
    creation_event = Event(
        event_id=event_dict["event_id"],
        room_id=room_id,
        sender=creator_mxid,
        event_type="m.room.create",
        content=event_dict["content"],
        origin_server_ts=datetime.fromtimestamp(event_dict["origin_server_ts"] / 1000),
        signatures=signed_event_dict.get("signatures")
    )
    await db.events.insert_one(creation_event.dict())
    
    # Auto-join creator to room
    member_data = RoomMember(
        room_id=room_id,
        user_mxid=creator_mxid,
        membership="join",
        power_level=100  # Admin power level
    )
    await db.room_members.insert_one(member_data.dict())
    
    return {
        "room_id": room_id,
        "room_alias": f"#{request.name or 'room'}:{SERVER_NAME}" if request.name else None,
        "server_name": SERVER_NAME
    }

@api_router.post("/rooms/{room_id}/join")
async def join_room(room_id: str, current_user: dict = Depends(get_current_active_user)):
    """Join a Matrix room"""
    user_mxid = current_user["mxid"]
    
    # Check if room exists
    room = await db.rooms.find_one({"room_id": room_id})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check if already joined
    existing_member = await db.room_members.find_one({
        "room_id": room_id,
        "user_mxid": user_mxid,
        "membership": "join"
    })
    
    if not existing_member:
        # Create join event
        event_dict = {
            "event_id": MatrixID.event_id(),
            "room_id": room_id,
            "sender": user_mxid,
            "type": "m.room.member",
            "content": {
                "membership": "join",
                "displayname": "Admin User"
            },
            "state_key": user_mxid,
            "origin_server_ts": int(time.time() * 1000)
        }
        
        # Sign the event
        signed_event_dict = matrix_signing.sign_json(event_dict)
        
        # Create Event object for MongoDB storage
        join_event = Event(
            event_id=event_dict["event_id"],
            room_id=room_id,
            sender=user_mxid,
            event_type="m.room.member",
            content=event_dict["content"],
            state_key=user_mxid,
            origin_server_ts=datetime.fromtimestamp(event_dict["origin_server_ts"] / 1000),
            signatures=signed_event_dict.get("signatures")
        )
        await db.events.insert_one(join_event.dict())
        
        # Add membership record
        member_data = RoomMember(
            room_id=room_id,
            user_mxid=user_mxid,
            membership="join"
        )
        await db.room_members.insert_one(member_data.dict())
    
    return {
        "event_id": MatrixID.event_id(),
        "room_id": room_id,
        "state": "joined"
    }

@api_router.post("/rooms/{room_id}/send/m.room.message")
async def send_message(room_id: str, message: SendMessageRequest, current_user: dict = Depends(get_current_active_user)):
    """Send a message to a Matrix room"""
    user_mxid = current_user["mxid"]
    
    # Check if room exists
    room = await db.rooms.find_one({"room_id": room_id})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check if user is member of room
    member = await db.room_members.find_one({
        "room_id": room_id,
        "user_mxid": user_mxid,
        "membership": "join"
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this room")
    
    # Create message event
    event_dict = {
        "event_id": MatrixID.event_id(),
        "room_id": room_id,
        "sender": user_mxid,
        "type": "m.room.message",
        "content": {
            "msgtype": message.msgtype,
            "body": message.body
        },
        "origin_server_ts": int(time.time() * 1000)
    }
    
    # Sign the event
    signed_event_dict = matrix_signing.sign_json(event_dict)
    
    # Create Event object for MongoDB storage
    message_event = Event(
        event_id=event_dict["event_id"],
        room_id=room_id,
        sender=user_mxid,
        event_type="m.room.message",
        content=event_dict["content"],
        origin_server_ts=datetime.fromtimestamp(event_dict["origin_server_ts"] / 1000),
        signatures=signed_event_dict.get("signatures")
    )
    await db.events.insert_one(message_event.dict())
    
    # Broadcast message to all connected clients in the room
    broadcast_message = {
        "type": "new_message",
        "data": {
            "event_id": message_event.event_id,
            "room_id": room_id,
            "sender": user_mxid,
            "content": message_event.content,
            "origin_server_ts": event_dict["origin_server_ts"],
            "timestamp": datetime.fromtimestamp(event_dict["origin_server_ts"] / 1000).isoformat()
        }
    }
    
    await manager.broadcast_to_room(room_id, broadcast_message)
    logger.info(f"Message broadcasted to room {room_id}")
    
    return {
        "event_id": message_event.event_id,
        "room_id": room_id,
        "sent": True
    }

@api_router.get("/rooms/{room_id}/messages")
async def get_room_messages(room_id: str, limit: int = 50, current_user: dict = Depends(get_current_active_user)):
    """Get messages from a room"""
    user_mxid = current_user["mxid"]
    
    # Check if room exists
    room = await db.rooms.find_one({"room_id": room_id})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check if user is member of the room
    membership = await db.room_members.find_one({
        "room_id": room_id,
        "user_mxid": user_mxid,
        "membership": "join"
    })
    if not membership:
        raise HTTPException(status_code=403, detail="Access denied to this room")
    
    # Get recent messages
    messages_cursor = db.events.find({
        "room_id": room_id,
        "event_type": "m.room.message"
    }).sort("origin_server_ts", -1).limit(limit)
    
    messages = await messages_cursor.to_list(limit)
    
    # Convert ObjectId to string and clean up the data
    cleaned_messages = []
    for msg in messages:
        # Convert ObjectId to string
        if "_id" in msg:
            msg["_id"] = str(msg["_id"])
        
        # Create clean message dict
        clean_msg = {
            "event_id": msg.get("event_id"),
            "room_id": msg.get("room_id"),
            "sender": msg.get("sender"),
            "event_type": msg.get("event_type"),
            "content": msg.get("content", {}),
            "origin_server_ts": msg.get("origin_server_ts").isoformat() if msg.get("origin_server_ts") else None,
            "signatures": msg.get("signatures")
        }
        cleaned_messages.append(clean_msg)
    
    # Reverse to get chronological order
    cleaned_messages.reverse()
    
    return {
        "messages": cleaned_messages,
        "room_id": room_id
    }

@api_router.get("/rooms")
async def get_user_rooms(current_user: dict = Depends(get_current_active_user)):
    """Get rooms for current user"""
    user_mxid = current_user["mxid"]
    
    # Get user's room memberships
    memberships = await db.room_members.find({
        "user_mxid": user_mxid,
        "membership": "join"
    }).to_list(None)
    
    room_ids = [m["room_id"] for m in memberships]
    
    if not room_ids:
        return {"rooms": []}
    
    # Get room details
    rooms_cursor = db.rooms.find({
        "room_id": {"$in": room_ids}
    })
    rooms = await rooms_cursor.to_list(None)
    
    # Convert ObjectId to string and clean up the data
    cleaned_rooms = []
    for room in rooms:
        # Convert ObjectId to string
        if "_id" in room:
            room["_id"] = str(room["_id"])
        
        # Remove any other non-serializable fields and create clean room dict
        clean_room = {
            "room_id": room.get("room_id"),
            "name": room.get("name"),
            "topic": room.get("topic"),
            "is_public": room.get("is_public", True),
            "creator_mxid": room.get("creator_mxid"),
            "created_at": room.get("created_at").isoformat() if room.get("created_at") else None
        }
        cleaned_rooms.append(clean_room)
    
    return {"rooms": cleaned_rooms}

# Federation API endpoints
@app.get("/_matrix/federation/v1/version")
async def federation_version():
    """Matrix federation version endpoint"""
    return {
        "server": {
            "name": "LibraChat",
            "version": "1.0.0"
        }
    }

@app.get("/_matrix/federation/v1/publicRooms")
async def get_public_rooms():
    """Get list of public rooms for federation"""
    # Get public rooms
    public_rooms = await db.rooms.find({"is_public": True}).to_list(None)
    
    chunk = []
    for room in public_rooms:
        # Get member count
        member_count = await db.room_members.count_documents({
            "room_id": room["room_id"],
            "membership": "join"
        })
        
        chunk.append({
            "aliases": [f"#{room['name']}:{SERVER_NAME}"] if room.get('name') else [],
            "avatar_url": room.get("avatar_url"),
            "canonical_alias": f"#{room['name']}:{SERVER_NAME}" if room.get('name') else None,
            "guest_can_join": True,
            "join_rule": "public",
            "name": room.get("name", "Unnamed Room"),
            "num_joined_members": member_count,
            "room_id": room["room_id"],
            "topic": room.get("topic"),
            "world_readable": True
        })
    
    return {
        "chunk": chunk,
        "next_batch": None,
        "prev_batch": None,
        "total_room_count_estimate": len(chunk)
    }

# Basic status endpoints
@api_router.get("/")
async def root():
    return {
        "server": "LibraChat Federation Server",
        "version": "1.0.0",
        "matrix_server": SERVER_NAME,
        "federation_ready": True
    }

@api_router.get("/server/info")
async def server_info():
    """Get server information"""
    # Get statistics
    room_count = await db.rooms.count_documents({})
    user_count = await db.room_members.distinct("user_mxid")
    event_count = await db.events.count_documents({})
    
    return {
        "server_name": SERVER_NAME,
        "version": "1.0.0",
        "federation_enabled": True,
        "verify_key": matrix_signing.get_verify_key_base64(),
        "statistics": {
            "room_count": room_count,
            "user_count": len(user_count),
            "event_count": event_count
        }
    }

# Include router
app.include_router(api_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize database indexes on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database indexes and server"""
    # Create indexes for better performance
    await db.users.create_index("mxid", unique=True)
    await db.rooms.create_index("room_id", unique=True)
    await db.events.create_index("event_id", unique=True)
    await db.events.create_index([("room_id", 1), ("origin_server_ts", -1)])
    await db.room_members.create_index([("room_id", 1), ("user_mxid", 1)])
    await db.server_keys.create_index([("server_name", 1), ("key_id", 1)])
    
    # New indexes for contacts and private messaging
    await db.contacts.create_index([("user_mxid", 1), ("contact_mxid", 1)], unique=True)
    await db.contacts.create_index("user_mxid")
    await db.private_messages.create_index([("sender_mxid", 1), ("recipient_mxid", 1), ("timestamp", -1)])
    await db.private_messages.create_index("message_id", unique=True)
    
    logger.info(f"LibraChat Federation Server started for {SERVER_NAME}")
    logger.info(f"Server signing key: {matrix_signing.get_verify_key_base64()}")
    logger.info("MongoDB indexes created successfully")

@app.on_event("shutdown")
async def shutdown_event():
    client.close()