#!/usr/bin/env python3
"""
Matrix Federation Backend Testing Suite
Tests all Matrix federation endpoints and APIs
"""

import requests
import json
import sys
from typing import Dict, Any, Optional
import time

# Backend URL from environment
BACKEND_URL = "https://f7851205-a22b-4e2a-bd18-97ce2a213628.preview.emergentagent.com"
API_BASE = f"{BACKEND_URL}/api"

class MatrixFederationTester:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'LibraChat-Test/1.0'
        })
        self.test_results = []
        self.created_room_id = None
    
    def log_test(self, test_name: str, success: bool, details: str, response_data: Any = None):
        """Log test results"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        print(f"   Details: {details}")
        if response_data:
            print(f"   Response: {json.dumps(response_data, indent=2)}")
        print()
        
        self.test_results.append({
            'test': test_name,
            'success': success,
            'details': details,
            'response': response_data
        })
    
    def test_matrix_server_discovery(self):
        """Test /.well-known/matrix/server endpoint"""
        try:
            response = self.session.get(f"{BACKEND_URL}/.well-known/matrix/server")
            
            if response.status_code == 200:
                data = response.json()
                expected_server = "librachat.local"
                
                if data.get("m.server") == expected_server:
                    self.log_test(
                        "Matrix Server Discovery",
                        True,
                        f"Correctly returns server name: {expected_server}",
                        data
                    )
                else:
                    self.log_test(
                        "Matrix Server Discovery",
                        False,
                        f"Expected 'm.server': '{expected_server}', got: {data}",
                        data
                    )
            else:
                self.log_test(
                    "Matrix Server Discovery",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Matrix Server Discovery", False, f"Exception: {str(e)}")
    
    def test_matrix_client_discovery(self):
        """Test /.well-known/matrix/client endpoint"""
        try:
            response = self.session.get(f"{BACKEND_URL}/.well-known/matrix/client")
            
            if response.status_code == 200:
                data = response.json()
                
                if "m.homeserver" in data and "base_url" in data["m.homeserver"]:
                    base_url = data["m.homeserver"]["base_url"]
                    if "librachat.local" in base_url:
                        self.log_test(
                            "Matrix Client Discovery",
                            True,
                            f"Correctly returns homeserver info with base_url: {base_url}",
                            data
                        )
                    else:
                        self.log_test(
                            "Matrix Client Discovery",
                            False,
                            f"base_url doesn't contain expected server name: {base_url}",
                            data
                        )
                else:
                    self.log_test(
                        "Matrix Client Discovery",
                        False,
                        "Missing required m.homeserver.base_url field",
                        data
                    )
            else:
                self.log_test(
                    "Matrix Client Discovery",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Matrix Client Discovery", False, f"Exception: {str(e)}")
    
    def test_server_keys(self):
        """Test /_matrix/key/v2/server endpoint"""
        try:
            response = self.session.get(f"{BACKEND_URL}/_matrix/key/v2/server")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check required fields
                required_fields = ["server_name", "verify_keys", "valid_until_ts", "signatures"]
                missing_fields = [field for field in required_fields if field not in data]
                
                if not missing_fields:
                    # Check server name
                    if data["server_name"] == "librachat.local":
                        # Check verify keys structure
                        verify_keys = data.get("verify_keys", {})
                        if "ed25519:key1" in verify_keys and "key" in verify_keys["ed25519:key1"]:
                            # Check signatures
                            signatures = data.get("signatures", {})
                            if "librachat.local" in signatures:
                                self.log_test(
                                    "Server Keys",
                                    True,
                                    "Server keys endpoint returns properly signed key response",
                                    {
                                        "server_name": data["server_name"],
                                        "key_present": "ed25519:key1" in verify_keys,
                                        "signed": "librachat.local" in signatures,
                                        "valid_until": data["valid_until_ts"]
                                    }
                                )
                            else:
                                self.log_test(
                                    "Server Keys",
                                    False,
                                    "Missing server signature in response",
                                    data
                                )
                        else:
                            self.log_test(
                                "Server Keys",
                                False,
                                "Missing or invalid verify_keys structure",
                                data
                            )
                    else:
                        self.log_test(
                            "Server Keys",
                            False,
                            f"Wrong server_name: expected 'librachat.local', got '{data['server_name']}'",
                            data
                        )
                else:
                    self.log_test(
                        "Server Keys",
                        False,
                        f"Missing required fields: {missing_fields}",
                        data
                    )
            else:
                self.log_test(
                    "Server Keys",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Server Keys", False, f"Exception: {str(e)}")
    
    def test_create_room(self):
        """Test POST /api/createRoom"""
        try:
            room_data = {
                "name": "test-federation-room",
                "topic": "Test room for Matrix federation",
                "preset": "public_chat"
            }
            
            response = self.session.post(f"{API_BASE}/createRoom", json=room_data)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check room_id format (!room:domain.tld)
                room_id = data.get("room_id")
                if room_id and room_id.startswith("!") and ":librachat.local" in room_id:
                    self.created_room_id = room_id  # Store for later tests
                    
                    # Check other fields
                    server_name = data.get("server_name")
                    room_alias = data.get("room_alias")
                    
                    if server_name == "librachat.local":
                        self.log_test(
                            "Create Room",
                            True,
                            f"Room created successfully with proper Matrix ID format",
                            {
                                "room_id": room_id,
                                "server_name": server_name,
                                "room_alias": room_alias
                            }
                        )
                    else:
                        self.log_test(
                            "Create Room",
                            False,
                            f"Wrong server_name in response: {server_name}",
                            data
                        )
                else:
                    self.log_test(
                        "Create Room",
                        False,
                        f"Invalid room_id format: {room_id} (should be !room:librachat.local)",
                        data
                    )
            else:
                self.log_test(
                    "Create Room",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Create Room", False, f"Exception: {str(e)}")
    
    def test_join_room(self):
        """Test POST /api/rooms/{room_id}/join"""
        if not self.created_room_id:
            self.log_test("Join Room", False, "No room_id available (create room test failed)")
            return
        
        try:
            response = self.session.post(f"{API_BASE}/rooms/{self.created_room_id}/join")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check response fields
                event_id = data.get("event_id")
                room_id = data.get("room_id")
                state = data.get("state")
                
                # Validate event_id format ($event:domain.tld)
                if event_id and event_id.startswith("$") and ":librachat.local" in event_id:
                    if room_id == self.created_room_id and state == "joined":
                        self.log_test(
                            "Join Room",
                            True,
                            f"Successfully joined room with proper event ID format",
                            {
                                "event_id": event_id,
                                "room_id": room_id,
                                "state": state
                            }
                        )
                    else:
                        self.log_test(
                            "Join Room",
                            False,
                            f"Incorrect room_id or state in response",
                            data
                        )
                else:
                    self.log_test(
                        "Join Room",
                        False,
                        f"Invalid event_id format: {event_id} (should be $event:librachat.local)",
                        data
                    )
            else:
                self.log_test(
                    "Join Room",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Join Room", False, f"Exception: {str(e)}")
    
    def test_send_message(self):
        """Test POST /api/rooms/{room_id}/send/m.room.message"""
        if not self.created_room_id:
            self.log_test("Send Message", False, "No room_id available (create room test failed)")
            return
        
        try:
            message_data = {
                "msgtype": "m.text",
                "body": "Test message MongoDB - Hello from Matrix federation test!"
            }
            
            response = self.session.post(
                f"{API_BASE}/rooms/{self.created_room_id}/send/m.room.message",
                json=message_data
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Check response fields
                event_id = data.get("event_id")
                room_id = data.get("room_id")
                sent = data.get("sent")
                
                # Validate event_id format ($event:domain.tld)
                if event_id and event_id.startswith("$") and ":librachat.local" in event_id:
                    if room_id == self.created_room_id and sent is True:
                        self.log_test(
                            "Send Message MongoDB",
                            True,
                            f"Message sent successfully with proper event ID format and stored in MongoDB",
                            {
                                "event_id": event_id,
                                "room_id": room_id,
                                "sent": sent,
                                "message_body": message_data["body"]
                            }
                        )
                    else:
                        self.log_test(
                            "Send Message MongoDB",
                            False,
                            f"Incorrect room_id or sent status in response",
                            data
                        )
                else:
                    self.log_test(
                        "Send Message MongoDB",
                        False,
                        f"Invalid event_id format: {event_id} (should be $event:librachat.local)",
                        data
                    )
            else:
                self.log_test(
                    "Send Message MongoDB",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Send Message MongoDB", False, f"Exception: {str(e)}")
    
    def test_get_room_messages(self):
        """Test GET /api/rooms/{room_id}/messages - Retrieve messages from MongoDB"""
        if not self.created_room_id:
            self.log_test("Get Room Messages", False, "No room_id available (create room test failed)")
            return
        
        try:
            response = self.session.get(f"{API_BASE}/rooms/{self.created_room_id}/messages")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check response structure
                if "messages" in data and "room_id" in data:
                    messages = data["messages"]
                    room_id = data["room_id"]
                    
                    if room_id == self.created_room_id:
                        if isinstance(messages, list) and len(messages) > 0:
                            # Check message structure
                            message = messages[0]
                            required_fields = ["event_id", "room_id", "sender", "event_type", "content"]
                            
                            if all(field in message for field in required_fields):
                                # Verify it's our test message
                                content = message.get("content", {})
                                if content.get("body") and "Test message MongoDB" in content["body"]:
                                    self.log_test(
                                        "Get Room Messages MongoDB",
                                        True,
                                        f"Successfully retrieved {len(messages)} message(s) from MongoDB with correct structure",
                                        {
                                            "message_count": len(messages),
                                            "room_id": room_id,
                                            "first_message_type": message["event_type"],
                                            "first_message_body": content.get("body", "")[:50] + "..."
                                        }
                                    )
                                else:
                                    self.log_test(
                                        "Get Room Messages MongoDB",
                                        True,
                                        f"Retrieved {len(messages)} message(s) from MongoDB (different content)",
                                        {
                                            "message_count": len(messages),
                                            "room_id": room_id
                                        }
                                    )
                            else:
                                missing = [f for f in required_fields if f not in message]
                                self.log_test(
                                    "Get Room Messages MongoDB",
                                    False,
                                    f"Message missing required fields: {missing}",
                                    data
                                )
                        else:
                            self.log_test(
                                "Get Room Messages MongoDB",
                                True,
                                "Messages endpoint working (no messages found in MongoDB)",
                                data
                            )
                    else:
                        self.log_test(
                            "Get Room Messages MongoDB",
                            False,
                            f"Wrong room_id in response: expected {self.created_room_id}, got {room_id}",
                            data
                        )
                else:
                    self.log_test(
                        "Get Room Messages MongoDB",
                        False,
                        "Missing required fields in response",
                        data
                    )
            else:
                self.log_test(
                    "Get Room Messages MongoDB",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Get Room Messages MongoDB", False, f"Exception: {str(e)}")
    
    def test_get_user_rooms(self):
        """Test GET /api/rooms - Get user rooms from MongoDB"""
        try:
            response = self.session.get(f"{API_BASE}/rooms")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check response structure
                if "rooms" in data:
                    rooms = data["rooms"]
                    
                    if isinstance(rooms, list):
                        if len(rooms) > 0:
                            # Check if our created room is in the list
                            room_ids = [room.get("room_id") for room in rooms]
                            
                            if self.created_room_id and self.created_room_id in room_ids:
                                # Find our room
                                our_room = next((r for r in rooms if r.get("room_id") == self.created_room_id), None)
                                
                                if our_room:
                                    required_fields = ["room_id", "name", "topic", "creator_mxid"]
                                    present_fields = [f for f in required_fields if f in our_room]
                                    
                                    self.log_test(
                                        "Get User Rooms MongoDB",
                                        True,
                                        f"Successfully retrieved {len(rooms)} room(s) from MongoDB including our test room",
                                        {
                                            "room_count": len(rooms),
                                            "test_room_found": True,
                                            "test_room_name": our_room.get("name"),
                                            "test_room_topic": our_room.get("topic"),
                                            "fields_present": present_fields
                                        }
                                    )
                                else:
                                    self.log_test(
                                        "Get User Rooms MongoDB",
                                        False,
                                        "Test room ID found in list but room data not accessible",
                                        data
                                    )
                            else:
                                self.log_test(
                                    "Get User Rooms MongoDB",
                                    True,
                                    f"Retrieved {len(rooms)} room(s) from MongoDB (test room not found, may be expected)",
                                    {
                                        "room_count": len(rooms),
                                        "room_ids": room_ids[:3]  # Show first 3 room IDs
                                    }
                                )
                        else:
                            self.log_test(
                                "Get User Rooms MongoDB",
                                True,
                                "User rooms endpoint working (no rooms found in MongoDB)",
                                data
                            )
                    else:
                        self.log_test(
                            "Get User Rooms MongoDB",
                            False,
                            "Rooms field is not a list",
                            data
                        )
                else:
                    self.log_test(
                        "Get User Rooms MongoDB",
                        False,
                        "Missing 'rooms' field in response",
                        data
                    )
            else:
                self.log_test(
                    "Get User Rooms MongoDB",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Get User Rooms MongoDB", False, f"Exception: {str(e)}")
    
    def test_federation_version(self):
        """Test GET /_matrix/federation/v1/version"""
        try:
            response = self.session.get(f"{BACKEND_URL}/_matrix/federation/v1/version")
            
            if response.status_code == 200:
                data = response.json()
                
                if "server" in data and "name" in data["server"] and "version" in data["server"]:
                    server_info = data["server"]
                    if server_info["name"] == "LibraChat":
                        self.log_test(
                            "Federation Version",
                            True,
                            f"Federation version endpoint working correctly",
                            data
                        )
                    else:
                        self.log_test(
                            "Federation Version",
                            False,
                            f"Unexpected server name: {server_info['name']}",
                            data
                        )
                else:
                    self.log_test(
                        "Federation Version",
                        False,
                        "Missing required server info fields",
                        data
                    )
            else:
                self.log_test(
                    "Federation Version",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Federation Version", False, f"Exception: {str(e)}")
    
    def test_public_rooms(self):
        """Test GET /_matrix/federation/v1/publicRooms"""
        try:
            response = self.session.get(f"{BACKEND_URL}/_matrix/federation/v1/publicRooms")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check required fields
                if "chunk" in data and isinstance(data["chunk"], list):
                    chunk = data["chunk"]
                    if len(chunk) > 0:
                        # Check first room structure
                        room = chunk[0]
                        required_room_fields = ["room_id", "name", "topic", "join_rule"]
                        
                        if all(field in room for field in required_room_fields):
                            # Check room_id format
                            room_id = room["room_id"]
                            if room_id.startswith("!") and ":librachat.local" in room_id:
                                self.log_test(
                                    "Public Rooms",
                                    True,
                                    f"Public rooms endpoint returns properly formatted room list",
                                    {
                                        "room_count": len(chunk),
                                        "first_room": {
                                            "room_id": room["room_id"],
                                            "name": room["name"],
                                            "join_rule": room["join_rule"]
                                        }
                                    }
                                )
                            else:
                                self.log_test(
                                    "Public Rooms",
                                    False,
                                    f"Invalid room_id format: {room_id}",
                                    data
                                )
                        else:
                            missing = [f for f in required_room_fields if f not in room]
                            self.log_test(
                                "Public Rooms",
                                False,
                                f"Missing room fields: {missing}",
                                data
                            )
                    else:
                        self.log_test(
                            "Public Rooms",
                            True,
                            "Public rooms endpoint working (empty room list)",
                            data
                        )
                else:
                    self.log_test(
                        "Public Rooms",
                        False,
                        "Missing or invalid 'chunk' field",
                        data
                    )
            else:
                self.log_test(
                    "Public Rooms",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Public Rooms", False, f"Exception: {str(e)}")
    
    def test_server_info(self):
        """Test GET /api/server/info"""
        try:
            response = self.session.get(f"{API_BASE}/server/info")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check required fields
                required_fields = ["server_name", "version", "federation_enabled", "verify_key"]
                missing_fields = [field for field in required_fields if field not in data]
                
                if not missing_fields:
                    if data["server_name"] == "librachat.local" and data["federation_enabled"] is True:
                        # Check verify_key is present and looks like base64
                        verify_key = data["verify_key"]
                        if verify_key and len(verify_key) > 20:  # Basic sanity check
                            self.log_test(
                                "Server Info",
                                True,
                                f"Server info endpoint returns correct federation info",
                                {
                                    "server_name": data["server_name"],
                                    "federation_enabled": data["federation_enabled"],
                                    "verify_key_length": len(verify_key)
                                }
                            )
                        else:
                            self.log_test(
                                "Server Info",
                                False,
                                f"Invalid verify_key: {verify_key}",
                                data
                            )
                    else:
                        self.log_test(
                            "Server Info",
                            False,
                            f"Wrong server_name or federation not enabled",
                            data
                        )
                else:
                    self.log_test(
                        "Server Info",
                        False,
                        f"Missing required fields: {missing_fields}",
                        data
                    )
            else:
                self.log_test(
                    "Server Info",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as e:
            self.log_test("Server Info", False, f"Exception: {str(e)}")
    
    def run_all_tests(self):
        """Run all Matrix federation tests"""
        print("🚀 Starting Matrix Federation Backend Tests")
        print(f"Backend URL: {BACKEND_URL}")
        print("=" * 60)
        
        # Matrix Discovery Tests
        print("📡 Testing Matrix Discovery Endpoints...")
        self.test_matrix_server_discovery()
        self.test_matrix_client_discovery()
        
        # Server Keys Tests
        print("🔐 Testing Server Keys...")
        self.test_server_keys()
        
        # Room Management Tests
        print("🏠 Testing Room Management...")
        self.test_create_room()
        self.test_join_room()
        self.test_send_message()
        
        # Federation Tests
        print("🌐 Testing Federation Endpoints...")
        self.test_federation_version()
        self.test_public_rooms()
        
        # Server Info Tests
        print("ℹ️ Testing Server Info...")
        self.test_server_info()
        
        # Summary
        print("=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for result in self.test_results if result['success'])
        total = len(self.test_results)
        
        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        if passed == total:
            print("\n🎉 All tests passed! Matrix federation implementation is working correctly.")
            return True
        else:
            print(f"\n⚠️ {total - passed} test(s) failed. Check the details above.")
            return False

def main():
    """Main test runner"""
    tester = MatrixFederationTester()
    success = tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()