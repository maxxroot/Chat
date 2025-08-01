import React, { useState, useEffect, useRef } from "react";
import "./App.css";
import axios from "axios";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import AuthModal from "./components/AuthModal";
import UserProfile from "./components/UserProfile";
import DiscordSidebar from "./components/DiscordSidebar";
import PrivateChat from "./components/PrivateChat";
import InviteUsersModal from "./components/InviteUsersModal";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Main Chat Component (needs authentication)
function ChatApp() {
  const { user, isAuthenticated } = useAuth();
  const [serverInfo, setServerInfo] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [currentRoom, setCurrentRoom] = useState(null);
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState("");
  const [newRoomName, setNewRoomName] = useState("");
  const [connectionStatus, setConnectionStatus] = useState("disconnected");
  const [wsConnectionStatus, setWsConnectionStatus] = useState("disconnected");
  const [showProfile, setShowProfile] = useState(false);
  
  // New states for private messaging
  const [selectedContact, setSelectedContact] = useState(null);
  const [chatMode, setChatMode] = useState('room'); // 'room' or 'private'
  
  // States for invite modal
  const [showInviteModal, setShowInviteModal] = useState(false);
  
  // Long polling référence
  const pollingRef = useRef(null);
  const isPollingRef = useRef(false);
  const lastTimestampRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const messagesEndRef = useRef(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Fetch user's rooms on startup
  useEffect(() => {
    if (isAuthenticated) {
      fetchServerInfo();
      fetchUserRooms();
    }
  }, [isAuthenticated]);

  // Long polling management
  useEffect(() => {
    if (currentRoom && isAuthenticated) {
      startLongPolling(currentRoom.room_id);
    }
    
    return () => {
      stopLongPolling();
    };
  }, [currentRoom, isAuthenticated]);

  // Cleanup long polling on component unmount
  useEffect(() => {
    return () => {
      stopLongPolling();
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);

  const startLongPolling = (roomId) => {
    if (!roomId || !isAuthenticated || isPollingRef.current) return;
    
    // Stop existing polling
    stopLongPolling();
    
    isPollingRef.current = true;
    setWsConnectionStatus("connected");
    
    console.log('Starting long polling for room:', roomId);
    
    const poll = async () => {
      try {
        console.log('Long polling request for room:', roomId);
        
        const response = await axios.get(`${API}/rooms/${roomId}/poll?timeout=30`, {
          timeout: 35000 // 35 seconds timeout (longer than server timeout)
        });
        
        if (response.data.messages && response.data.messages.length > 0) {
          console.log('Received long polling messages:', response.data.messages);
          
          response.data.messages.forEach(messageData => {
            if (messageData.type === 'new_message' && messageData.data) {
              const newMessage = {
                event_id: messageData.data.event_id,
                sender: messageData.data.sender,
                content: messageData.data.content,
                origin_server_ts: messageData.data.origin_server_ts
              };
              
              setMessages(prevMessages => {
                // Check if message already exists to avoid duplicates
                const messageExists = prevMessages.some(msg => msg.event_id === newMessage.event_id);
                if (messageExists) return prevMessages;
                
                console.log('Adding new message via long polling:', newMessage);
                return [...prevMessages, newMessage];
              });
            }
          });
        }
        
        // Immediately start next poll if still active
        if (isPollingRef.current && currentRoom?.room_id === roomId) {
          setTimeout(() => poll(), 0);
        }
        
      } catch (error) {
        console.error('Long polling error:', error);
        
        if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
          // Timeout is normal, immediately restart polling
          console.log('Long polling timeout, restarting...');
          if (isPollingRef.current && currentRoom?.room_id === roomId) {
            setTimeout(() => poll(), 0);
          }
        } else {
          // Other errors - set error status and retry after delay
          setWsConnectionStatus("error");
          
          if (isPollingRef.current && currentRoom?.room_id === roomId) {
            setTimeout(() => {
              setWsConnectionStatus("connected");
              poll();
            }, 3000);
          }
        }
      }
    };
    
    // Start polling immediately
    poll();
  };

  const stopLongPolling = () => {
    if (isPollingRef.current) {
      console.log('Stopping long polling');
      isPollingRef.current = false;
      setWsConnectionStatus("disconnected");
    }
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  };

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
      setRooms([]);
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
      
      // Refresh rooms list to get the created room
      fetchUserRooms();
    } catch (error) {
      console.error("Failed to create room:", error);
    }
  };

  const joinRoom = async (room) => {
    try {
      await axios.post(`${API}/rooms/${room.room_id}/join`);
      
      // Clear messages when switching rooms
      setMessages([]);
      setCurrentRoom(room);
      setChatMode('room');
      setSelectedContact(null);
      
      // Load existing messages
      await loadRoomMessages(room.room_id);
    } catch (error) {
      console.error("Failed to join room:", error);
    }
  };

  const handleSelectContact = (contact) => {
    setSelectedContact(contact);
    setChatMode('private');
    setCurrentRoom(null);
    setMessages([]);
    
    // Stop long polling from room
    stopLongPolling();
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
      
      console.log('Message sent:', response.data);
      
      // Clear the input - message will be added via WebSocket
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

  const getWsConnectionStatusColor = () => {
    switch (wsConnectionStatus) {
      case "connected": return "text-green-400";
      case "error": return "text-red-400";
      default: return "text-yellow-400";
    }
  };

  if (!isAuthenticated) {
    return null; // This component should only render when authenticated
  }

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
                {currentRoom && (
                  <div className={`connection-status ${getWsConnectionStatusColor()}`}>
                    <div className="status-dot"></div>
                    <span>WS: {wsConnectionStatus}</span>
                  </div>
                )}
                <div className="federation-info">
                  <span className="label">Federation:</span>
                  <span className="value">{serverInfo.federation_enabled ? "Enabled" : "Disabled"}</span>
                </div>
              </>
            )}
            
            {/* User Info */}
            <div className="user-info">
              <span className="user-display-name">{user?.display_name}</span>
              {user?.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt="Avatar"
                  className="user-avatar"
                  onClick={() => setShowProfile(true)}
                />
              ) : (
                <div
                  className="user-avatar-placeholder"
                  onClick={() => setShowProfile(true)}
                >
                  {user?.display_name?.charAt(0)?.toUpperCase() || user?.localpart?.charAt(0)?.toUpperCase()}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="main-content">
        {/* Discord-like Sidebar */}
        <DiscordSidebar
          rooms={rooms}
          currentRoom={currentRoom}
          onJoinRoom={joinRoom}
          onCreateRoom={createRoom}
          newRoomName={newRoomName}
          setNewRoomName={setNewRoomName}
          selectedContact={selectedContact}
          onSelectContact={handleSelectContact}
        />

        {/* Chat Area */}
        <div className="chat-area">
          {chatMode === 'private' ? (
            <PrivateChat contact={selectedContact} />
          ) : currentRoom ? (
            <>
              <div className="chat-header">
                <div className="room-info">
                  <h2>#{currentRoom.name}</h2>
                  <div className="room-details">
                    <span className="room-id-display">{currentRoom.room_id}</span>
                    {currentRoom.topic && <span className="topic">{currentRoom.topic}</span>}
                  </div>
                </div>
                <div className="room-actions">
                  <button 
                    onClick={() => setShowInviteModal(true)}
                    className="invite-btn"
                    title="Invite users to this room"
                  >
                    <span className="invite-icon">👥</span>
                    Invite Users
                  </button>
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
                        <div>WebSocket: <span className={getWsConnectionStatusColor()}>{wsConnectionStatus}</span></div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    {messages.map((message) => (
                      <div key={message.event_id} className="message">
                        <div className="message-header">
                          <span className="sender">{message.sender}</span>
                          <span className="timestamp">
                            {new Date(message.origin_server_ts).toLocaleTimeString()}
                          </span>
                        </div>
                        <div className="message-content">{message.content.body}</div>
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                  </>
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
                <h2>Bienvenue, {user?.display_name} !</h2>
                <p>Votre plateforme de messagerie fédérée utilisant le protocole Matrix</p>
                
                <div className="features-grid">
                  <div className="feature-card">
                    <h3>🌐 Matrix Federation</h3>
                    <p>Connectez-vous avec d'autres instances LibraChat utilisant les standards du protocole Matrix</p>
                  </div>
                  <div className="feature-card">
                    <h3>🔒 Chiffrement E2E</h3>
                    <p>Messages privés chiffrés de bout en bout avec RSA+AES</p>
                  </div>
                  <div className="feature-card">
                    <h3>👥 Gestion des Contacts</h3>
                    <p>Recherchez et ajoutez des contacts locaux et fédérés</p>
                  </div>
                  <div className="feature-card">
                    <h3>⚡ Real-time</h3>
                    <p>Messagerie instantanée avec support WebSocket</p>
                  </div>
                </div>
                
                <div className="get-started">
                  <h3>Commencer</h3>
                  <p>Sélectionnez une salle dans l'onglet "Servers" ou ajoutez des contacts dans "Direct Messages" !</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      
      {/* Profile Modal */}
      <UserProfile
        isOpen={showProfile}
        onClose={() => setShowProfile(false)}
      />
      
      {/* Invite Users Modal */}
      <InviteUsersModal
        isOpen={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        roomId={currentRoom?.room_id}
        roomName={currentRoom?.name}
      />
    </div>
  );
}

// Landing Page Component (for non-authenticated users)
function LandingPage({ onShowAuth }) {
  return (
    <div className="app-container">
      <div className="header">
        <div className="header-content">
          <div className="logo-section">
            <h1 className="logo">LibraChat</h1>
            <span className="subtitle">Federated Messaging</span>
          </div>
          
          <div className="auth-buttons">
            <button
              onClick={onShowAuth}
              className="auth-btn login"
            >
              Se connecter
            </button>
            <button
              onClick={onShowAuth}
              className="auth-btn register"
            >
              S'inscrire
            </button>
          </div>
        </div>
      </div>

      <div className="no-room-selected">
        <div className="welcome-section">
          <h2>Bienvenue sur LibraChat</h2>
          <p>Une plateforme de messagerie fédérée utilisant le protocole Matrix</p>
          
          <div className="features-grid">
            <div className="feature-card">
              <h3>🌐 Matrix Federation</h3>
              <p>Connectez-vous avec d'autres instances LibraChat utilisant les standards du protocole Matrix</p>
            </div>
            <div className="feature-card">
              <h3>🔒 Chiffrement E2E</h3>
              <p>Messages privés chiffrés de bout en bout avec RSA+AES</p>
            </div>
            <div className="feature-card">
              <h3>👥 Gestion des Contacts</h3>
              <p>Recherchez et ajoutez des contacts locaux et fédérés</p>
            </div>
            <div className="feature-card">
              <h3>⚡ Real-time</h3>
              <p>Messagerie instantanée avec support WebSocket</p>
            </div>
          </div>
          
          <div className="get-started">
            <h3>Commencer</h3>
            <p>Créez un compte ou connectez-vous pour accéder à vos salles de discussion fédérées et vos contacts !</p>
            <button
              onClick={onShowAuth}
              className="auth-btn register"
              style={{ marginTop: '1rem', padding: '0.75rem 2rem' }}
            >
              Commencer maintenant
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Main App with Auth Provider
function App() {
  const [showAuthModal, setShowAuthModal] = useState(false);
  
  return (
    <AuthProvider>
      <MainAppContent setShowAuthModal={setShowAuthModal} />
      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
      />
    </AuthProvider>
  );
}

// Main Content Component
function MainAppContent({ setShowAuthModal }) {
  const { isAuthenticated, loading } = useAuth();
  
  if (loading) {
    return (
      <div className="app-container">
        <div className="loading-screen">
          <h1>LibraChat</h1>
          <p>Chargement...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LandingPage onShowAuth={() => setShowAuthModal(true)} />;
  }

  return <ChatApp />;
}

export default App;