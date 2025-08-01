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
from cryptography.hazmat.primitives.asymmetric import ed25519
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
async def create_room(request: CreateRoomRequest):
    """Create a new Matrix room"""
    room_id = MatrixID.room_id()
    creator_mxid = MatrixID.user_id("admin")
    
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
async def join_room(room_id: str):
    """Join a Matrix room"""
    user_mxid = MatrixID.user_id("admin")  # For now, default user
    
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
async def send_message(room_id: str, message: SendMessageRequest):
    """Send a message to a Matrix room"""
    user_mxid = MatrixID.user_id("admin")
    
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
async def get_room_messages(room_id: str, limit: int = 50):
    """Get messages from a room"""
    # Check if room exists
    room = await db.rooms.find_one({"room_id": room_id})
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
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
async def get_user_rooms():
    """Get rooms for current user"""
    user_mxid = MatrixID.user_id("admin")
    
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
    
    logger.info(f"LibraChat Federation Server started for {SERVER_NAME}")
    logger.info(f"Server signing key: {matrix_signing.get_verify_key_base64()}")
    logger.info("MongoDB indexes created successfully")

@app.on_event("shutdown")
async def shutdown_event():
    client.close()