import React, { useState, useEffect } from "react";
import "./App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function App() {
  const [serverInfo, setServerInfo] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [currentRoom, setCurrentRoom] = useState(null);
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState("");
  const [newRoomName, setNewRoomName] = useState("");
  const [connectionStatus, setConnectionStatus] = useState("disconnected");

  // Fetch user's rooms on startup
  useEffect(() => {
    fetchServerInfo();
    fetchUserRooms();
  }, []);

  const fetchServerInfo = async () => {
    try {
      const response = await axios.get(`${API}/server/info`);
      setServerInfo(response.data);
      setConnectionStatus("connected");
    } catch (error) {
      console.error("Failed to fetch server info:", error);
      setConnectionStatus("error");
    }
  };

  const fetchUserRooms = async () => {
    try {
      const response = await axios.get(`${API}/rooms`);
      setRooms(response.data.rooms || []);
    } catch (error) {
      console.error("Failed to fetch rooms:", error);
      // Fallback to default room
      setRooms([
        {
          room_id: `!general:${serverInfo?.server_name || 'librachat.local'}`,
          name: "General",
          topic: "General discussion room"
        }
      ]);
    }
  };

  const createRoom = async () => {
    if (!newRoomName.trim()) return;
    
    try {
      const response = await axios.post(`${API}/createRoom`, {
        name: newRoomName,
        topic: `Room for ${newRoomName} discussion`,
        preset: "public_chat"
      });
      
      const newRoom = {
        room_id: response.data.room_id,
        name: newRoomName,
        topic: `Room for ${newRoomName} discussion`
      };
      
      setRooms([...rooms, newRoom]);
      setNewRoomName("");
    } catch (error) {
      console.error("Failed to create room:", error);
    }
  };

  const joinRoom = async (room) => {
    try {
      await axios.post(`${API}/rooms/${room.room_id}/join`);
      setCurrentRoom(room);
      
      // Load existing messages
      await loadRoomMessages(room.room_id);
    } catch (error) {
      console.error("Failed to join room:", error);
    }
  };

  const loadRoomMessages = async (roomId) => {
    try {
      const response = await axios.get(`${API}/rooms/${roomId}/messages?limit=50`);
      const loadedMessages = response.data.messages.map(msg => ({
        event_id: msg.event_id,
        sender: msg.sender,
        content: msg.content,
        origin_server_ts: new Date(msg.origin_server_ts).getTime()
      }));
      setMessages(loadedMessages);
    } catch (error) {
      console.error("Failed to load messages:", error);
      setMessages([]);
    }
  };

  const sendMessage = async () => {
    if (!newMessage.trim() || !currentRoom) return;
    
    try {
      const response = await axios.post(
        `${API}/rooms/${currentRoom.room_id}/send/m.room.message`,
        {
          msgtype: "m.text",
          body: newMessage
        }
      );
      
      // Add message to local state
      const message = {
        event_id: response.data.event_id,
        sender: "@admin:librachat.local",
        content: { body: newMessage },
        origin_server_ts: Date.now()
      };
      
      setMessages([...messages, message]);
      setNewMessage("");
    } catch (error) {
      console.error("Failed to send message:", error);
    }
  };

  const getConnectionStatusColor = () => {
    switch (connectionStatus) {
      case "connected": return "text-green-400";
      case "error": return "text-red-400";
      default: return "text-yellow-400";
    }
  };

  return (
    <div className="app-container">
      {/* Header with Federation Info */}
      <div className="header">
        <div className="header-content">
          <div className="logo-section">
            <h1 className="logo">LibraChat</h1>
            <span className="subtitle">Federated Messaging</span>
          </div>
          
          <div className="server-info">
            {serverInfo && (
              <>
                <div className="server-name">
                  <span className="label">Server:</span>
                  <span className="value">{serverInfo.server_name}</span>
                </div>
                <div className={`connection-status ${getConnectionStatusColor()}`}>
                  <div className="status-dot"></div>
                  <span>{connectionStatus}</span>
                </div>
                <div className="federation-info">
                  <span className="label">Federation:</span>
                  <span className="value">{serverInfo.federation_enabled ? "Enabled" : "Disabled"}</span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="main-content">
        {/* Sidebar - Rooms */}
        <div className="sidebar">
          <div className="sidebar-header">
            <h3>Rooms</h3>
            <div className="create-room-section">
              <input
                type="text"
                placeholder="New room name"
                value={newRoomName}
                onChange={(e) => setNewRoomName(e.target.value)}
                className="room-input"
                onKeyPress={(e) => e.key === 'Enter' && createRoom()}
              />
              <button onClick={createRoom} className="create-btn">+</button>
            </div>
          </div>
          
          <div className="rooms-list">
            {rooms.map((room) => (
              <div
                key={room.room_id}
                className={`room-item ${currentRoom?.room_id === room.room_id ? 'active' : ''}`}
                onClick={() => joinRoom(room)}
              >
                <div className="room-name">#{room.name}</div>
                <div className="room-id">{room.room_id}</div>
                {room.topic && <div className="room-topic">{room.topic}</div>}
              </div>
            ))}
          </div>
          
          {/* Matrix Federation Info */}
          <div className="federation-panel">
            <h4>Matrix Federation</h4>
            <div className="federation-details">
              <div className="detail-item">
                <span className="label">Homeserver:</span>
                <span className="value">{serverInfo?.server_name}</span>
              </div>
              <div className="detail-item">
                <span className="label">User ID:</span>
                <span className="value">@admin:{serverInfo?.server_name}</span>
              </div>
              <div className="detail-item">
                <span className="label">Signing Key:</span>
                <span className="value key-display">{serverInfo?.verify_key?.substring(0, 16)}...</span>
              </div>
            </div>
          </div>
        </div>

        {/* Chat Area */}
        <div className="chat-area">
          {currentRoom ? (
            <>
              <div className="chat-header">
                <h2>#{currentRoom.name}</h2>
                <div className="room-details">
                  <span className="room-id-display">{currentRoom.room_id}</span>
                  {currentRoom.topic && <span className="topic">{currentRoom.topic}</span>}
                </div>
              </div>
              
              <div className="messages-container">
                {messages.length === 0 ? (
                  <div className="no-messages">
                    <h3>Welcome to #{currentRoom.name}</h3>
                    <p>This is the beginning of your conversation in this federated room.</p>
                    <div className="federation-info-box">
                      <h4>🌐 Matrix Federation Active</h4>
                      <p>This room uses the Matrix protocol for federation. Messages sent here can be synchronized with other LibraChat instances.</p>
                      <div className="room-specs">
                        <div>Room ID: <code>{currentRoom.room_id}</code></div>
                        <div>Server: <code>{serverInfo?.server_name}</code></div>
                      </div>
                    </div>
                  </div>
                ) : (
                  messages.map((message) => (
                    <div key={message.event_id} className="message">
                      <div className="message-header">
                        <span className="sender">{message.sender}</span>
                        <span className="timestamp">
                          {new Date(message.origin_server_ts).toLocaleTimeString()}
                        </span>
                      </div>
                      <div className="message-content">{message.content.body}</div>
                    </div>
                  ))
                )}
              </div>
              
              <div className="message-input-container">
                <input
                  type="text"
                  placeholder={`Message #${currentRoom.name}`}
                  value={newMessage}
                  onChange={(e) => setNewMessage(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
                  className="message-input"
                />
                <button onClick={sendMessage} className="send-btn">Send</button>
              </div>
            </>
          ) : (
            <div className="no-room-selected">
              <div className="welcome-section">
                <h2>Welcome to LibraChat</h2>
                <p>A federated messaging platform using the Matrix protocol</p>
                
                <div className="features-grid">
                  <div className="feature-card">
                    <h3>🌐 Matrix Federation</h3>
                    <p>Connect with other LibraChat instances using Matrix protocol standards</p>
                  </div>
                  <div className="feature-card">
                    <h3>🔒 Future E2EE</h3>
                    <p>End-to-end encryption support planned with Olm/Double Ratchet</p>
                  </div>
                  <div className="feature-card">
                    <h3>🏠 Self-Hosted</h3>
                    <p>Run your own instance with full control over your data</p>
                  </div>
                  <div className="feature-card">
                    <h3>⚡ Real-time</h3>
                    <p>Instant messaging with WebSocket support</p>
                  </div>
                </div>
                
                <div className="get-started">
                  <h3>Get Started</h3>
                  <p>Select a room from the sidebar or create a new one to begin chatting!</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;