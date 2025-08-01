from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
import os
import logging
import json
import time
import hashlib
import hmac
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import base64
import canonicaljson
from signedjson import key, sign
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Database setup
DATABASE_URL = os.environ['DATABASE_URL']
SERVER_NAME = os.environ['SERVER_NAME']
SIGNING_KEY_SEED = os.environ['SIGNING_KEY_SEED']

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

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

# Database Models
class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mxid = Column(String, unique=True, nullable=False)  # @user:domain.tld
    localpart = Column(String, nullable=False)
    server_name = Column(String, nullable=False)
    display_name = Column(String)
    avatar_url = Column(String)
    password_hash = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Room(Base):
    __tablename__ = "rooms"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(String, unique=True, nullable=False)  # !room:domain.tld
    name = Column(String)
    topic = Column(Text)
    avatar_url = Column(String)
    is_public = Column(Boolean, default=True)
    creator_mxid = Column(String, nullable=False)
    version = Column(String, default="1")
    created_at = Column(DateTime, default=datetime.utcnow)

class RoomMember(Base):
    __tablename__ = "room_members"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(String, nullable=False)
    user_mxid = Column(String, nullable=False)
    membership = Column(String, default="join")  # join, leave, invite, ban
    power_level = Column(Integer, default=0)
    joined_at = Column(DateTime, default=datetime.utcnow)

class Event(Base):
    __tablename__ = "events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String, unique=True, nullable=False)
    room_id = Column(String, nullable=False)
    sender = Column(String, nullable=False)
    event_type = Column(String, nullable=False)  # m.room.message, m.room.member, etc.
    content = Column(Text, nullable=False)  # JSON
    state_key = Column(String)  # For state events
    origin_server_ts = Column(DateTime, default=datetime.utcnow)
    signatures = Column(Text)  # JSON of signatures

class ServerKey(Base):
    __tablename__ = "server_keys"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_name = Column(String, nullable=False)
    key_id = Column(String, nullable=False)
    verify_key = Column(Text, nullable=False)
    valid_until_ts = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

# Pydantic Models
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
        canonical = canonicaljson.encode_canonical_json(signed)
        signature = self.signing_key.sign(canonical)
        signature_base64 = base64.b64encode(signature).decode()
        
        if "signatures" not in signed:
            signed["signatures"] = {}
        if SERVER_NAME not in signed["signatures"]:
            signed["signatures"][SERVER_NAME] = {}
        
        signed["signatures"][SERVER_NAME][f"ed25519:key1"] = signature_base64
        return signed

# Initialize signing
matrix_signing = MatrixSigning()

# Create the main app
app = FastAPI(title="LibraChat Federation Server")
api_router = APIRouter(prefix="/api")

# Database dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

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

# Room Creation and Management
@api_router.post("/createRoom")
async def create_room(request: CreateRoomRequest):
    """Create a new Matrix room"""
    room_id = MatrixID.room_id()
    
    # Create room creation event
    creation_content = {
        "creator": MatrixID.user_id("admin"),
        "room_version": "1"
    }
    
    if request.name:
        creation_content["name"] = request.name
    if request.topic:
        creation_content["topic"] = request.topic
    
    room_data = {
        "room_id": room_id,
        "name": request.name,
        "topic": request.topic,
        "creator_mxid": MatrixID.user_id("admin"),
        "is_public": request.preset == "public_chat"
    }
    
    return {
        "room_id": room_id,
        "room_alias": f"#{request.name or 'room'}:{SERVER_NAME}" if request.name else None,
        "server_name": SERVER_NAME
    }

@api_router.post("/rooms/{room_id}/join")
async def join_room(room_id: str):
    """Join a Matrix room"""
    user_mxid = MatrixID.user_id("admin")  # For now, default user
    
    # Create join event
    join_event = {
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
    signed_event = matrix_signing.sign_json(join_event)
    
    return {
        "event_id": join_event["event_id"],
        "room_id": room_id,
        "state": "joined"
    }

@api_router.post("/rooms/{room_id}/send/m.room.message")
async def send_message(room_id: str, message: SendMessageRequest):
    """Send a message to a Matrix room"""
    user_mxid = MatrixID.user_id("admin")
    
    message_event = {
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
    signed_event = matrix_signing.sign_json(message_event)
    
    return {
        "event_id": message_event["event_id"],
        "room_id": room_id,
        "sent": True
    }

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
    return {
        "chunk": [
            {
                "aliases": [f"#general:{SERVER_NAME}"],
                "avatar_url": None,
                "canonical_alias": f"#general:{SERVER_NAME}",
                "guest_can_join": True,
                "join_rule": "public",
                "name": "General",
                "num_joined_members": 1,
                "room_id": f"!general:{SERVER_NAME}",
                "topic": "General discussion room",
                "world_readable": True
            }
        ],
        "next_batch": None,
        "prev_batch": None,
        "total_room_count_estimate": 1
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
    return {
        "server_name": SERVER_NAME,
        "version": "1.0.0",
        "federation_enabled": True,
        "verify_key": matrix_signing.get_verify_key_base64()
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

# Create tables on startup
@app.on_event("startup")
async def startup_event():
    """Create database tables and initialize server"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"LibraChat Federation Server started for {SERVER_NAME}")
    logger.info(f"Server signing key: {matrix_signing.get_verify_key_base64()}")

@app.on_event("shutdown")
async def shutdown_event():
    await engine.dispose()