import React, { useState } from 'react';
import ContactsList from './ContactsList';

const DiscordSidebar = ({ 
  rooms, 
  currentRoom, 
  onJoinRoom, 
  onCreateRoom,
  newRoomName, 
  setNewRoomName,
  selectedContact,
  onSelectContact 
}) => {
  const [activeTab, setActiveTab] = useState('servers'); // 'servers' or 'dms'

  return (
    <div className="discord-sidebar">
      {/* Tab Navigation */}
      <div className="sidebar-tabs">
        <button
          className={`sidebar-tab ${activeTab === 'servers' ? 'active' : ''}`}
          onClick={() => setActiveTab('servers')}
        >
          <span className="tab-icon">🏠</span>
          <span className="tab-label">Servers</span>
        </button>
        <button
          className={`sidebar-tab ${activeTab === 'dms' ? 'active' : ''}`}
          onClick={() => setActiveTab('dms')}
        >
          <span className="tab-icon">💬</span>
          <span className="tab-label">Direct Messages</span>
        </button>
      </div>

      {/* Tab Content */}
      <div className="sidebar-content">
        {activeTab === 'servers' ? (
          <div className="servers-section">
            <div className="section-header">
              <h3>Rooms</h3>
              <div className="create-room-section">
                <input
                  type="text"
                  placeholder="New room name"
                  value={newRoomName}
                  onChange={(e) => setNewRoomName(e.target.value)}
                  className="room-input"
                  onKeyPress={(e) => e.key === 'Enter' && onCreateRoom()}
                />
                <button onClick={onCreateRoom} className="create-btn">+</button>
              </div>
            </div>
            
            <div className="rooms-list">
              {rooms.map((room) => (
                <div
                  key={room.room_id}
                  className={`room-item ${currentRoom?.room_id === room.room_id ? 'active' : ''}`}
                  onClick={() => onJoinRoom(room)}
                >
                  <div className="room-icon">#</div>
                  <div className="room-info">
                    <div className="room-name">{room.name}</div>
                    {room.topic && <div className="room-topic">{room.topic}</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <ContactsList 
            onSelectContact={onSelectContact}
            selectedContact={selectedContact}
          />
        )}
      </div>
    </div>
  );
};

export default DiscordSidebar;