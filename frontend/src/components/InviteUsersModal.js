import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const InviteUsersModal = ({ isOpen, onClose, roomId, roomName }) => {
  const { user } = useAuth();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedUsers, setSelectedUsers] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isInviting, setIsInviting] = useState(false);
  const [members, setMembers] = useState([]);
  const debounceRef = useRef(null);

  useEffect(() => {
    if (isOpen && roomId) {
      fetchRoomMembers();
    }
  }, [isOpen, roomId]);

  const fetchRoomMembers = async () => {
    try {
      const response = await axios.get(`${API}/rooms/${roomId}/members`);
      setMembers(response.data.members || []);
    } catch (error) {
      console.error('Failed to fetch room members:', error);
    }
  };

  const searchUsers = async (query) => {
    if (!query.trim()) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    try {
      console.log('Searching for:', query.trim());
      console.log('API URL:', `${API}/contacts/search`);
      console.log('Auth headers:', axios.defaults.headers.common);
      
      const response = await axios.post(`${API}/contacts/search`, {
        query: query.trim()
      });
      
      console.log('Search response:', response.data);
      setSearchResults(response.data.users || []);
    } catch (error) {
      console.error('Search failed:', error);
      console.error('Error response:', error.response?.data);
      console.error('Error status:', error.response?.status);
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  const handleSearchChange = (e) => {
    const query = e.target.value;
    setSearchQuery(query);
    
    // Debounce search
    setTimeout(() => {
      if (query === searchQuery) {
        searchUsers(query);
      }
    }, 300);
  };

  const toggleUserSelection = (user) => {
    setSelectedUsers(prev => {
      const isSelected = prev.some(u => u.mxid === user.mxid);
      if (isSelected) {
        return prev.filter(u => u.mxid !== user.mxid);
      } else {
        return [...prev, user];
      }
    });
  };

  const inviteUsers = async () => {
    if (selectedUsers.length === 0) return;

    setIsInviting(true);
    try {
      const response = await axios.post(`${API}/rooms/${roomId}/invite`, {
        user_mxids: selectedUsers.map(u => u.mxid)
      });

      const { invited_users, errors, success_count } = response.data;
      
      if (success_count > 0) {
        alert(`Successfully invited ${success_count} user(s) to ${roomName}`);
        setSelectedUsers([]);
        setSearchQuery('');
        setSearchResults([]);
        fetchRoomMembers(); // Refresh members list
        onClose();
      }
      
      if (errors.length > 0) {
        alert(`Some invitations failed:\n${errors.join('\n')}`);
      }
    } catch (error) {
      console.error('Failed to invite users:', error);
      alert('Failed to invite users: ' + (error.response?.data?.detail || error.message));
    } finally {
      setIsInviting(false);
    }
  };

  const isUserAlreadyMember = (userMxid) => {
    return members.some(member => member.mxid === userMxid);
  };

  const isUserSelected = (userMxid) => {
    return selectedUsers.some(u => u.mxid === userMxid);
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="invite-modal">
        <div className="modal-header">
          <h3>Invite Users to #{roomName}</h3>
          <button onClick={onClose} className="modal-close">×</button>
        </div>
        
        <div className="modal-body">
          {/* Search Section */}
          <div className="search-section">
            <input
              type="text"
              placeholder="Search users by name or @user:domain"
              value={searchQuery}
              onChange={handleSearchChange}
              className="search-input"
            />
          </div>

          {/* Selected Users */}
          {selectedUsers.length > 0 && (
            <div className="selected-users">
              <h4>Selected Users ({selectedUsers.length})</h4>
              <div className="selected-users-list">
                {selectedUsers.map(user => (
                  <div key={user.mxid} className="selected-user-item">
                    <div className="user-info">
                      <div className="user-avatar-placeholder">
                        {user.display_name?.charAt(0)?.toUpperCase() || user.localpart?.charAt(0)?.toUpperCase()}
                      </div>
                      <div className="user-details">
                        <div className="user-name">{user.display_name || user.localpart}</div>
                        <div className="user-mxid">{user.mxid}</div>
                      </div>
                    </div>
                    <button 
                      onClick={() => toggleUserSelection(user)}
                      className="remove-user-btn"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Search Results */}
          {searchQuery && (
            <div className="search-results">
              <h4>Search Results</h4>
              {isSearching ? (
                <div className="loading-state">Searching...</div>
              ) : searchResults.length > 0 ? (
                <div className="search-results-list">
                  {searchResults.map(user => {
                    const isAlreadyMember = isUserAlreadyMember(user.mxid);
                    const isSelected = isUserSelected(user.mxid);
                    
                    return (
                      <div key={user.mxid} className="search-result-item">
                        <div className="user-info">
                          <div className="user-avatar-placeholder">
                            {user.display_name?.charAt(0)?.toUpperCase() || user.localpart?.charAt(0)?.toUpperCase()}
                          </div>
                          <div className="user-details">
                            <div className="user-name">{user.display_name || user.localpart}</div>
                            <div className="user-mxid">{user.mxid}</div>
                            {user.is_federated && <div className="federated-badge">Federated</div>}
                          </div>
                        </div>
                        
                        {isAlreadyMember ? (
                          <span className="already-member">Already member</span>
                        ) : (
                          <button 
                            onClick={() => toggleUserSelection(user)}
                            className={`select-user-btn ${isSelected ? 'selected' : ''}`}
                          >
                            {isSelected ? 'Selected' : 'Select'}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="no-results">No users found</div>
              )}
            </div>
          )}

          {/* Current Members */}
          <div className="current-members">
            <h4>Current Members ({members.length})</h4>
            <div className="members-list">
              {members.map(member => (
                <div key={member.mxid} className="member-item">
                  <div className="user-avatar-placeholder">
                    {member.display_name?.charAt(0)?.toUpperCase() || member.mxid?.charAt(1)?.toUpperCase()}
                  </div>
                  <div className="member-details">
                    <div className="member-name">{member.display_name || member.mxid.split(':')[0].substring(1)}</div>
                    <div className="member-mxid">{member.mxid}</div>
                  </div>
                  {member.mxid === user?.mxid && (
                    <span className="self-badge">You</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
        
        <div className="modal-footer">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button 
            onClick={inviteUsers} 
            className="btn-primary"
            disabled={selectedUsers.length === 0 || isInviting}
          >
            {isInviting ? 'Inviting...' : `Invite ${selectedUsers.length} User(s)`}
          </button>
        </div>
      </div>
    </div>
  );
};

export default InviteUsersModal;