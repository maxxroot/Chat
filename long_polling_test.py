#!/usr/bin/env python3
"""
LibraChat Long Polling System Testing Suite
Tests the completely rewritten long polling system for real-time messaging
"""

import requests
import json
import sys
import time
import threading
from typing import Dict, Any, Optional
import asyncio
import concurrent.futures

# Backend URL from environment
BACKEND_URL = "https://8e248d07-7114-4a71-8ae4-a767a612c721.preview.emergentagent.com"
API_BASE = f"{BACKEND_URL}/api"

class LongPollingTester:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'LibraChat-LongPolling-Test/1.0'
        })
        self.test_results = []
        self.user1_token = None
        self.user2_token = None
        self.user1_mxid = None
        self.user2_mxid = None
        self.test_room_id = None
        # Generate unique suffix for this test run
        import random
        self.suffix = random.randint(10000, 99999)
    
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
    
    def setup_test_users_and_room(self):
        """Setup two test users and create a room for testing"""
        try:
            # Register first user
            user1_data = {
                "username": f"alice_poll_{self.suffix}",
                "email": f"alice_poll_{self.suffix}@example.com",
                "password": "securepass123",
                "display_name": "Alice Polling"
            }
            
            response = self.session.post(f"{API_BASE}/auth/register", json=user1_data)
            
            if response.status_code == 200:
                data = response.json()
                self.user1_token = data["access_token"]
                self.user1_mxid = data["user"]["mxid"]
                
                self.log_test(
                    "Setup User 1",
                    True,
                    f"User 1 registered successfully: {self.user1_mxid}",
                    {"mxid": self.user1_mxid}
                )
            else:
                self.log_test("Setup User 1", False, f"HTTP {response.status_code}: {response.text}")
                return False
                
            # Register second user
            user2_data = {
                "username": f"bob_poll_{self.suffix}",
                "email": f"bob_poll_{self.suffix}@example.com", 
                "password": "strongpass456",
                "display_name": "Bob Polling"
            }
            
            response = self.session.post(f"{API_BASE}/auth/register", json=user2_data)
            
            if response.status_code == 200:
                data = response.json()
                self.user2_token = data["access_token"]
                self.user2_mxid = data["user"]["mxid"]
                
                self.log_test(
                    "Setup User 2",
                    True,
                    f"User 2 registered successfully: {self.user2_mxid}",
                    {"mxid": self.user2_mxid}
                )
            else:
                self.log_test("Setup User 2", False, f"HTTP {response.status_code}: {response.text}")
                return False
            
            # Create a test room
            headers = {"Authorization": f"Bearer {self.user1_token}"}
            room_data = {
                "name": f"Long Polling Test Room {self.suffix}",
                "topic": "Testing long polling functionality",
                "preset": "public_chat"
            }
            
            response = self.session.post(f"{API_BASE}/createRoom", json=room_data, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                self.test_room_id = data["room_id"]
                
                self.log_test(
                    "Setup Test Room",
                    True,
                    f"Test room created successfully: {self.test_room_id}",
                    {"room_id": self.test_room_id, "room_name": room_data["name"]}
                )
            else:
                self.log_test("Setup Test Room", False, f"HTTP {response.status_code}: {response.text}")
                return False
            
            # User 2 joins the room
            headers2 = {"Authorization": f"Bearer {self.user2_token}"}
            response = self.session.post(f"{API_BASE}/rooms/{self.test_room_id}/join", headers=headers2)
            
            if response.status_code == 200:
                self.log_test(
                    "Setup User 2 Join Room",
                    True,
                    f"User 2 joined room successfully",
                    {"room_id": self.test_room_id}
                )
                return True
            else:
                self.log_test("Setup User 2 Join Room", False, f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_test("Setup Test Users and Room", False, f"Exception: {str(e)}")
            return False
    
    def test_basic_long_polling_flow(self):
        """Test basic long polling flow - User A polls, User B sends message, User A receives it"""
        if not all([self.user1_token, self.user2_token, self.test_room_id]):
            self.log_test("Basic Long Polling Flow", False, "Missing required setup data")
            return
        
        try:
            # Start long polling in a separate thread for User 1
            polling_result = {"messages": None, "error": None, "completed": False}
            
            def start_polling():
                try:
                    headers = {"Authorization": f"Bearer {self.user1_token}"}
                    # Start polling with a 15-second timeout
                    response = self.session.get(
                        f"{API_BASE}/rooms/{self.test_room_id}/poll?timeout=15",
                        headers=headers,
                        timeout=20  # HTTP timeout slightly longer than polling timeout
                    )
                    
                    if response.status_code == 200:
                        polling_result["messages"] = response.json()
                    else:
                        polling_result["error"] = f"HTTP {response.status_code}: {response.text}"
                except Exception as e:
                    polling_result["error"] = str(e)
                finally:
                    polling_result["completed"] = True
            
            # Start polling thread
            polling_thread = threading.Thread(target=start_polling)
            polling_thread.start()
            
            # Wait a moment to ensure polling has started
            time.sleep(2)
            
            # User 2 sends a message to the room
            headers2 = {"Authorization": f"Bearer {self.user2_token}"}
            message_data = {
                "msgtype": "m.text",
                "body": f"Hello Alice! This is a real-time message via long polling. Test ID: {self.suffix}"
            }
            
            send_response = self.session.post(
                f"{API_BASE}/rooms/{self.test_room_id}/send/m.room.message",
                json=message_data,
                headers=headers2
            )
            
            if send_response.status_code != 200:
                self.log_test(
                    "Basic Long Polling Flow",
                    False,
                    f"Failed to send message: HTTP {send_response.status_code}: {send_response.text}"
                )
                return
            
            # Wait for polling to complete (should complete quickly after message is sent)
            polling_thread.join(timeout=20)  # Wait up to 20 seconds
            
            if not polling_result["completed"]:
                self.log_test(
                    "Basic Long Polling Flow",
                    False,
                    "Long polling did not complete within timeout"
                )
                return
            
            if polling_result["error"]:
                self.log_test(
                    "Basic Long Polling Flow",
                    False,
                    f"Long polling error: {polling_result['error']}"
                )
                return
            
            if polling_result["messages"]:
                messages_data = polling_result["messages"]
                
                # Check response structure
                if "messages" in messages_data and isinstance(messages_data["messages"], list):
                    messages = messages_data["messages"]
                    
                    if len(messages) > 0:
                        # Find our test message
                        found_message = None
                        for msg in messages:
                            if "data" in msg and "content" in msg["data"]:
                                content = msg["data"]["content"]
                                if isinstance(content, dict) and content.get("body", "").find(f"Test ID: {self.suffix}") != -1:
                                    found_message = msg
                                    break
                        
                        if found_message:
                            # Verify message details
                            msg_data = found_message["data"]
                            if (msg_data.get("sender") == self.user2_mxid and 
                                msg_data.get("room_id") == self.test_room_id):
                                
                                self.log_test(
                                    "Basic Long Polling Flow",
                                    True,
                                    f"✅ REAL-TIME MESSAGE DELIVERY WORKING! User A received message from User B via long polling within seconds",
                                    {
                                        "message_received": True,
                                        "sender": msg_data.get("sender"),
                                        "room_id": msg_data.get("room_id"),
                                        "content_preview": content.get("body", "")[:50] + "...",
                                        "timeout_reached": messages_data.get("timeout_reached", False),
                                        "timestamp": messages_data.get("timestamp")
                                    }
                                )
                            else:
                                self.log_test(
                                    "Basic Long Polling Flow",
                                    False,
                                    f"Message received but with wrong sender/room details",
                                    found_message
                                )
                        else:
                            self.log_test(
                                "Basic Long Polling Flow",
                                False,
                                f"Test message not found in polling results",
                                messages_data
                            )
                    else:
                        self.log_test(
                            "Basic Long Polling Flow",
                            False,
                            "No messages received via long polling",
                            messages_data
                        )
                else:
                    self.log_test(
                        "Basic Long Polling Flow",
                        False,
                        "Invalid polling response structure",
                        messages_data
                    )
            else:
                self.log_test(
                    "Basic Long Polling Flow",
                    False,
                    "No polling result received"
                )
                
        except Exception as e:
            self.log_test("Basic Long Polling Flow", False, f"Exception: {str(e)}")
    
    def test_timestamp_based_message_retrieval(self):
        """Test that the 'since' parameter works correctly and prevents message duplication"""
        if not all([self.user1_token, self.user2_token, self.test_room_id]):
            self.log_test("Timestamp-based Message Retrieval", False, "Missing required setup data")
            return
        
        try:
            headers1 = {"Authorization": f"Bearer {self.user1_token}"}
            headers2 = {"Authorization": f"Bearer {self.user2_token}"}
            
            # Get current timestamp
            initial_timestamp = time.time()
            
            # Send first message
            message1_data = {
                "msgtype": "m.text",
                "body": f"First message for timestamp test {self.suffix}"
            }
            
            response = self.session.post(
                f"{API_BASE}/rooms/{self.test_room_id}/send/m.room.message",
                json=message1_data,
                headers=headers2
            )
            
            if response.status_code != 200:
                self.log_test("Timestamp-based Message Retrieval", False, "Failed to send first message")
                return
            
            # Wait a moment
            time.sleep(1)
            
            # Poll for messages since initial timestamp
            response = self.session.get(
                f"{API_BASE}/rooms/{self.test_room_id}/poll?since={initial_timestamp}&timeout=5",
                headers=headers1
            )
            
            if response.status_code != 200:
                self.log_test("Timestamp-based Message Retrieval", False, f"First poll failed: HTTP {response.status_code}")
                return
            
            first_poll_data = response.json()
            first_poll_messages = first_poll_data.get("messages", [])
            
            if len(first_poll_messages) == 0:
                self.log_test("Timestamp-based Message Retrieval", False, "No messages in first poll")
                return
            
            # Get timestamp from first poll
            first_poll_timestamp = first_poll_data.get("timestamp", time.time())
            
            # Send second message
            time.sleep(1)
            message2_data = {
                "msgtype": "m.text",
                "body": f"Second message for timestamp test {self.suffix}"
            }
            
            response = self.session.post(
                f"{API_BASE}/rooms/{self.test_room_id}/send/m.room.message",
                json=message2_data,
                headers=headers2
            )
            
            if response.status_code != 200:
                self.log_test("Timestamp-based Message Retrieval", False, "Failed to send second message")
                return
            
            # Poll for messages since first poll timestamp
            response = self.session.get(
                f"{API_BASE}/rooms/{self.test_room_id}/poll?since={first_poll_timestamp}&timeout=5",
                headers=headers1
            )
            
            if response.status_code != 200:
                self.log_test("Timestamp-based Message Retrieval", False, f"Second poll failed: HTTP {response.status_code}")
                return
            
            second_poll_data = response.json()
            second_poll_messages = second_poll_data.get("messages", [])
            
            # Verify that second poll only contains new messages (not duplicates)
            if len(second_poll_messages) > 0:
                # Check that we don't get the first message again
                found_first_message = False
                found_second_message = False
                
                for msg in second_poll_messages:
                    if "data" in msg and "content" in msg["data"]:
                        content = msg["data"]["content"]
                        if isinstance(content, dict):
                            body = content.get("body", "")
                            if "First message for timestamp test" in body:
                                found_first_message = True
                            elif "Second message for timestamp test" in body:
                                found_second_message = True
                
                if found_second_message and not found_first_message:
                    self.log_test(
                        "Timestamp-based Message Retrieval",
                        True,
                        "✅ Timestamp-based filtering working correctly - no message duplication",
                        {
                            "first_poll_messages": len(first_poll_messages),
                            "second_poll_messages": len(second_poll_messages),
                            "found_first_message_in_second_poll": found_first_message,
                            "found_second_message_in_second_poll": found_second_message,
                            "first_poll_timestamp": first_poll_timestamp,
                            "second_poll_timestamp": second_poll_data.get("timestamp")
                        }
                    )
                else:
                    self.log_test(
                        "Timestamp-based Message Retrieval",
                        False,
                        f"Message filtering issue - found_first: {found_first_message}, found_second: {found_second_message}",
                        {
                            "first_poll_messages": len(first_poll_messages),
                            "second_poll_messages": len(second_poll_messages)
                        }
                    )
            else:
                self.log_test(
                    "Timestamp-based Message Retrieval",
                    False,
                    "No messages in second poll (expected at least the second message)",
                    second_poll_data
                )
                
        except Exception as e:
            self.log_test("Timestamp-based Message Retrieval", False, f"Exception: {str(e)}")
    
    def test_authentication_and_membership(self):
        """Test authentication and membership requirements for polling endpoint"""
        if not self.test_room_id:
            self.log_test("Authentication and Membership", False, "Missing test room ID")
            return
        
        try:
            # Test 1: Unauthenticated request should return 401/403
            response = self.session.get(f"{API_BASE}/rooms/{self.test_room_id}/poll?timeout=1")
            
            if response.status_code in [401, 403]:
                auth_test_passed = True
                auth_details = f"Unauthenticated request correctly rejected with HTTP {response.status_code}"
            else:
                auth_test_passed = False
                auth_details = f"Unauthenticated request should return 401/403, got {response.status_code}"
            
            # Test 2: Create a new user who is not a member of the room
            non_member_data = {
                "username": f"charlie_nonmember_{self.suffix}",
                "email": f"charlie_{self.suffix}@example.com",
                "password": "testpass789",
                "display_name": "Charlie Non-Member"
            }
            
            response = self.session.post(f"{API_BASE}/auth/register", json=non_member_data)
            
            if response.status_code == 200:
                non_member_token = response.json()["access_token"]
                
                # Try to poll the room as non-member
                headers = {"Authorization": f"Bearer {non_member_token}"}
                response = self.session.get(
                    f"{API_BASE}/rooms/{self.test_room_id}/poll?timeout=1",
                    headers=headers
                )
                
                if response.status_code == 403:
                    membership_test_passed = True
                    membership_details = "Non-member correctly rejected with HTTP 403"
                else:
                    membership_test_passed = False
                    membership_details = f"Non-member should get 403, got {response.status_code}: {response.text}"
            else:
                membership_test_passed = False
                membership_details = "Failed to create non-member user for testing"
            
            # Test 3: Valid member should be able to poll
            headers = {"Authorization": f"Bearer {self.user1_token}"}
            response = self.session.get(
                f"{API_BASE}/rooms/{self.test_room_id}/poll?timeout=1",
                headers=headers
            )
            
            if response.status_code == 200:
                member_test_passed = True
                member_details = "Valid member can poll successfully"
            else:
                member_test_passed = False
                member_details = f"Valid member polling failed: HTTP {response.status_code}: {response.text}"
            
            # Overall test result
            all_passed = auth_test_passed and membership_test_passed and member_test_passed
            
            self.log_test(
                "Authentication and Membership",
                all_passed,
                f"Auth test: {auth_details}. Membership test: {membership_details}. Member test: {member_details}",
                {
                    "auth_test_passed": auth_test_passed,
                    "membership_test_passed": membership_test_passed,
                    "member_test_passed": member_test_passed
                }
            )
                
        except Exception as e:
            self.log_test("Authentication and Membership", False, f"Exception: {str(e)}")
    
    def test_multiple_messages_rapid_fire(self):
        """Test sending multiple messages rapidly and verify they all arrive via polling"""
        if not all([self.user1_token, self.user2_token, self.test_room_id]):
            self.log_test("Multiple Messages Rapid Fire", False, "Missing required setup data")
            return
        
        try:
            headers1 = {"Authorization": f"Bearer {self.user1_token}"}
            headers2 = {"Authorization": f"Bearer {self.user2_token}"}
            
            # Start long polling
            polling_result = {"messages": None, "error": None, "completed": False}
            
            def start_polling():
                try:
                    response = self.session.get(
                        f"{API_BASE}/rooms/{self.test_room_id}/poll?timeout=10",
                        headers=headers1,
                        timeout=15
                    )
                    
                    if response.status_code == 200:
                        polling_result["messages"] = response.json()
                    else:
                        polling_result["error"] = f"HTTP {response.status_code}: {response.text}"
                except Exception as e:
                    polling_result["error"] = str(e)
                finally:
                    polling_result["completed"] = True
            
            polling_thread = threading.Thread(target=start_polling)
            polling_thread.start()
            
            # Wait for polling to start
            time.sleep(1)
            
            # Send multiple messages rapidly
            test_messages = [
                f"Rapid message 1 - {self.suffix}",
                f"Rapid message 2 - {self.suffix}",
                f"Rapid message 3 - {self.suffix}",
                f"Rapid message 4 - {self.suffix}",
                f"Rapid message 5 - {self.suffix}"
            ]
            
            for i, msg_text in enumerate(test_messages):
                message_data = {
                    "msgtype": "m.text",
                    "body": msg_text
                }
                
                response = self.session.post(
                    f"{API_BASE}/rooms/{self.test_room_id}/send/m.room.message",
                    json=message_data,
                    headers=headers2
                )
                
                if response.status_code != 200:
                    self.log_test(
                        "Multiple Messages Rapid Fire",
                        False,
                        f"Failed to send message {i+1}: HTTP {response.status_code}"
                    )
                    return
                
                # Small delay between messages
                time.sleep(0.2)
            
            # Wait for polling to complete
            polling_thread.join(timeout=15)
            
            if not polling_result["completed"]:
                self.log_test("Multiple Messages Rapid Fire", False, "Polling did not complete")
                return
            
            if polling_result["error"]:
                self.log_test("Multiple Messages Rapid Fire", False, f"Polling error: {polling_result['error']}")
                return
            
            if polling_result["messages"]:
                messages_data = polling_result["messages"]
                messages = messages_data.get("messages", [])
                
                # Count how many of our test messages were received
                received_messages = []
                for msg in messages:
                    if "data" in msg and "content" in msg["data"]:
                        content = msg["data"]["content"]
                        if isinstance(content, dict):
                            body = content.get("body", "")
                            for test_msg in test_messages:
                                if test_msg in body:
                                    received_messages.append(test_msg)
                                    break
                
                if len(received_messages) == len(test_messages):
                    self.log_test(
                        "Multiple Messages Rapid Fire",
                        True,
                        f"✅ All {len(test_messages)} rapid messages received via long polling",
                        {
                            "messages_sent": len(test_messages),
                            "messages_received": len(received_messages),
                            "total_polling_messages": len(messages)
                        }
                    )
                else:
                    self.log_test(
                        "Multiple Messages Rapid Fire",
                        False,
                        f"Only {len(received_messages)}/{len(test_messages)} messages received",
                        {
                            "messages_sent": len(test_messages),
                            "messages_received": len(received_messages),
                            "received_messages": received_messages
                        }
                    )
            else:
                self.log_test("Multiple Messages Rapid Fire", False, "No polling result received")
                
        except Exception as e:
            self.log_test("Multiple Messages Rapid Fire", False, f"Exception: {str(e)}")
    
    def test_timeout_behavior(self):
        """Test timeout behavior (30 second timeout)"""
        if not all([self.user1_token, self.test_room_id]):
            self.log_test("Timeout Behavior", False, "Missing required setup data")
            return
        
        try:
            headers = {"Authorization": f"Bearer {self.user1_token}"}
            
            # Test with short timeout (3 seconds) and no messages
            start_time = time.time()
            response = self.session.get(
                f"{API_BASE}/rooms/{self.test_room_id}/poll?timeout=3",
                headers=headers,
                timeout=10  # HTTP timeout longer than polling timeout
            )
            end_time = time.time()
            
            if response.status_code == 200:
                data = response.json()
                elapsed_time = end_time - start_time
                
                # Check that timeout was respected (should be around 3 seconds, allow some variance)
                if 2.5 <= elapsed_time <= 4.5:
                    if data.get("timeout_reached") is True and len(data.get("messages", [])) == 0:
                        self.log_test(
                            "Timeout Behavior",
                            True,
                            f"✅ Timeout behavior working correctly - returned after {elapsed_time:.1f}s with timeout_reached=True",
                            {
                                "requested_timeout": 3,
                                "actual_elapsed_time": elapsed_time,
                                "timeout_reached": data.get("timeout_reached"),
                                "messages_count": len(data.get("messages", []))
                            }
                        )
                    else:
                        self.log_test(
                            "Timeout Behavior",
                            False,
                            f"Timeout reached but response structure incorrect",
                            data
                        )
                else:
                    self.log_test(
                        "Timeout Behavior",
                        False,
                        f"Timeout not respected - elapsed time {elapsed_time:.1f}s (expected ~3s)",
                        {
                            "requested_timeout": 3,
                            "actual_elapsed_time": elapsed_time
                        }
                    )
            else:
                self.log_test(
                    "Timeout Behavior",
                    False,
                    f"HTTP {response.status_code}: {response.text}"
                )
                
        except Exception as e:
            self.log_test("Timeout Behavior", False, f"Exception: {str(e)}")
    
    def test_invalid_room_id(self):
        """Test with invalid room IDs"""
        if not self.user1_token:
            self.log_test("Invalid Room ID", False, "Missing user token")
            return
        
        try:
            headers = {"Authorization": f"Bearer {self.user1_token}"}
            
            # Test with non-existent room ID
            fake_room_id = "!nonexistent12345:librachat.local"
            response = self.session.get(
                f"{API_BASE}/rooms/{fake_room_id}/poll?timeout=1",
                headers=headers
            )
            
            # Should return 404 or 403 (depending on implementation)
            if response.status_code in [403, 404]:
                self.log_test(
                    "Invalid Room ID",
                    True,
                    f"✅ Invalid room ID correctly rejected with HTTP {response.status_code}",
                    {"room_id": fake_room_id, "status_code": response.status_code}
                )
            else:
                self.log_test(
                    "Invalid Room ID",
                    False,
                    f"Invalid room ID should return 403/404, got {response.status_code}: {response.text}"
                )
                
        except Exception as e:
            self.log_test("Invalid Room ID", False, f"Exception: {str(e)}")
    
    def test_messages_dont_go_back_to_sender(self):
        """Test that messages don't go back to the sender via polling"""
        if not all([self.user1_token, self.user2_token, self.test_room_id]):
            self.log_test("Messages Don't Go Back to Sender", False, "Missing required setup data")
            return
        
        try:
            headers1 = {"Authorization": f"Bearer {self.user1_token}"}
            headers2 = {"Authorization": f"Bearer {self.user2_token}"}
            
            # User 1 starts polling
            polling_result = {"messages": None, "error": None, "completed": False}
            
            def start_polling():
                try:
                    response = self.session.get(
                        f"{API_BASE}/rooms/{self.test_room_id}/poll?timeout=8",
                        headers=headers1,
                        timeout=12
                    )
                    
                    if response.status_code == 200:
                        polling_result["messages"] = response.json()
                    else:
                        polling_result["error"] = f"HTTP {response.status_code}: {response.text}"
                except Exception as e:
                    polling_result["error"] = str(e)
                finally:
                    polling_result["completed"] = True
            
            polling_thread = threading.Thread(target=start_polling)
            polling_thread.start()
            
            time.sleep(1)
            
            # User 1 sends a message (should NOT appear in their own polling)
            user1_message = {
                "msgtype": "m.text",
                "body": f"Message from User 1 - should not appear in own polling - {self.suffix}"
            }
            
            response = self.session.post(
                f"{API_BASE}/rooms/{self.test_room_id}/send/m.room.message",
                json=user1_message,
                headers=headers1
            )
            
            if response.status_code != 200:
                self.log_test("Messages Don't Go Back to Sender", False, "Failed to send User 1 message")
                return
            
            time.sleep(1)
            
            # User 2 sends a message (SHOULD appear in User 1's polling)
            user2_message = {
                "msgtype": "m.text",
                "body": f"Message from User 2 - should appear in User 1 polling - {self.suffix}"
            }
            
            response = self.session.post(
                f"{API_BASE}/rooms/{self.test_room_id}/send/m.room.message",
                json=user2_message,
                headers=headers2
            )
            
            if response.status_code != 200:
                self.log_test("Messages Don't Go Back to Sender", False, "Failed to send User 2 message")
                return
            
            # Wait for polling to complete
            polling_thread.join(timeout=15)
            
            if not polling_result["completed"]:
                self.log_test("Messages Don't Go Back to Sender", False, "Polling did not complete")
                return
            
            if polling_result["error"]:
                self.log_test("Messages Don't Go Back to Sender", False, f"Polling error: {polling_result['error']}")
                return
            
            if polling_result["messages"]:
                messages_data = polling_result["messages"]
                messages = messages_data.get("messages", [])
                
                found_user1_message = False
                found_user2_message = False
                
                for msg in messages:
                    if "data" in msg and "content" in msg["data"]:
                        content = msg["data"]["content"]
                        if isinstance(content, dict):
                            body = content.get("body", "")
                            sender = msg["data"].get("sender", "")
                            
                            if f"Message from User 1 - should not appear in own polling - {self.suffix}" in body:
                                found_user1_message = True
                            elif f"Message from User 2 - should appear in User 1 polling - {self.suffix}" in body:
                                found_user2_message = True
                
                if not found_user1_message and found_user2_message:
                    self.log_test(
                        "Messages Don't Go Back to Sender",
                        True,
                        "✅ Messages correctly filtered - User 1 didn't receive their own message but received User 2's message",
                        {
                            "found_own_message": found_user1_message,
                            "found_other_message": found_user2_message,
                            "total_messages": len(messages)
                        }
                    )
                else:
                    self.log_test(
                        "Messages Don't Go Back to Sender",
                        False,
                        f"Message filtering issue - own message found: {found_user1_message}, other message found: {found_user2_message}",
                        {
                            "found_own_message": found_user1_message,
                            "found_other_message": found_user2_message,
                            "total_messages": len(messages)
                        }
                    )
            else:
                self.log_test("Messages Don't Go Back to Sender", False, "No polling result received")
                
        except Exception as e:
            self.log_test("Messages Don't Go Back to Sender", False, f"Exception: {str(e)}")
    
    def run_all_tests(self):
        """Run all long polling tests"""
        print("🚀 Starting LibraChat Long Polling System Tests")
        print(f"Backend URL: {BACKEND_URL}")
        print("=" * 80)
        
        # Setup
        print("🔧 Setting up test environment...")
        if not self.setup_test_users_and_room():
            print("❌ Setup failed, aborting tests")
            return False
        
        print("\n📡 Testing Long Polling System...")
        
        # Core functionality tests
        self.test_basic_long_polling_flow()
        self.test_timestamp_based_message_retrieval()
        self.test_authentication_and_membership()
        
        # Performance and reliability tests
        self.test_multiple_messages_rapid_fire()
        self.test_timeout_behavior()
        self.test_invalid_room_id()
        self.test_messages_dont_go_back_to_sender()
        
        # Summary
        print("=" * 80)
        print("📊 LONG POLLING TEST SUMMARY")
        print("=" * 80)
        
        passed = sum(1 for result in self.test_results if result['success'])
        total = len(self.test_results)
        
        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        if passed == total:
            print("\n🎉 ALL LONG POLLING TESTS PASSED!")
            print("✅ Real-time message delivery: WORKING")
            print("✅ Timestamp-based message filtering: WORKING")
            print("✅ Authentication and membership checks: WORKING")
            print("✅ Multiple rapid messages: WORKING")
            print("✅ Timeout behavior: WORKING")
            print("✅ Error handling: WORKING")
            print("✅ Message sender filtering: WORKING")
            print("\n🚀 The long polling system is ready for production!")
            return True
        else:
            print(f"\n⚠️ {total - passed} test(s) failed. Check the details above.")
            
            # Show failed tests
            failed_tests = [result for result in self.test_results if not result['success']]
            if failed_tests:
                print("\n❌ FAILED TESTS:")
                for test in failed_tests:
                    print(f"   • {test['test']}: {test['details']}")
            
            return False

def main():
    """Main test runner"""
    tester = LongPollingTester()
    success = tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()