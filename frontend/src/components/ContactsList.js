import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const ContactsList = ({ onSelectContact, selectedContact }) => {
  const { user } = useAuth();
  const [contacts, setContacts] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchContacts();
    fetchConversations();
  }, []);

  const fetchContacts = async () => {
    try {
      const response = await axios.get(`${API}/contacts`);
      setContacts(response.data.contacts || []);
    } catch (error) {
      console.error('Failed to fetch contacts:', error);
    }
  };

  const fetchConversations = async () => {
    try {
      const response = await axios.get(`${API}/conversations`);
      setConversations(response.data.conversations || []);
    } catch (error) {
      console.error('Failed to fetch conversations:', error);
    }
  };

  const searchUsers = async (query) => {
    if (!query.trim()) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(`${API}/contacts/search`, {
        query: query.trim()
      });
      setSearchResults(response.data.users || []);
      setIsSearching(true);
    } catch (error) {
      console.error('Search failed:', error);
      setSearchResults([]);
    } finally {
      setLoading(false);
    }
  };

  const addContact = async (contactMxid) => {
    try {
      await axios.post(`${API}/contacts/add`, {
        contact_mxid: contactMxid
      });
      
      // Refresh contacts and conversations
      await fetchContacts();
      await fetchConversations();
      
      // Clear search
      setSearchQuery('');
      setSearchResults([]);
      setIsSearching(false);
    } catch (error) {
      console.error('Failed to add contact:', error);
      alert('Failed to add contact: ' + (error.response?.data?.detail || error.message));
    }
  };

  const removeContact = async (contactMxid) => {
    if (!confirm('Are you sure you want to remove this contact?')) return;

    try {
      await axios.delete(`${API}/contacts/${encodeURIComponent(contactMxid)}`);
      await fetchContacts();
      await fetchConversations();
      
      // If we're viewing this contact, clear selection
      if (selectedContact?.contact_mxid === contactMxid) {
        onSelectContact(null);
      }
    } catch (error) {
      console.error('Failed to remove contact:', error);
      alert('Failed to remove contact: ' + (error.response?.data?.detail || error.message));
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

  const clearSearch = () => {
    setSearchQuery('');
    setSearchResults([]);
    setIsSearching(false);
  };

  return (
    <div className="contacts-list">
      {/* Search Section */}
      <div className="contacts-search">
        <div className="search-input-container">
          <input
            type="text"
            placeholder="Search users by name or @user:domain"
            value={searchQuery}
            onChange={handleSearchChange}
            className="search-input"
          />
          {searchQuery && (
            <button onClick={clearSearch} className="search-clear">
              ×
            </button>
          )}
        </div>
      </div>

      {/* Search Results */}
      {isSearching && (
        <div className="search-results">
          <div className="section-header">
            <h4>Search Results</h4>
          </div>
          {loading ? (
            <div className="loading-state">Searching...</div>
          ) : searchResults.length > 0 ? (
            searchResults.map((user) => {
              const isAlreadyContact = contacts.some(c => c.contact_mxid === user.mxid);
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
                  {!isAlreadyContact ? (
                    <button 
                      onClick={() => addContact(user.mxid)}
                      className="add-contact-btn"
                    >
                      Add
                    </button>
                  ) : (
                    <span className="already-contact">Added</span>
                  )}
                </div>
              );
            })
          ) : (
            <div className="no-results">No users found</div>
          )}
        </div>
      )}

      {/* Conversations List */}
      {!isSearching && (
        <div className="conversations-section">
          <div className="section-header">
            <h4>Direct Messages</h4>
          </div>
          
          {conversations.length > 0 ? (
            conversations.map((conversation) => (
              <div
                key={conversation.contact_mxid}
                className={`conversation-item ${selectedContact?.contact_mxid === conversation.contact_mxid ? 'active' : ''}`}
                onClick={() => onSelectContact(conversation)}
              >
                <div className="user-avatar-placeholder">
                  {conversation.display_name?.charAt(0)?.toUpperCase() || conversation.contact_mxid?.charAt(1)?.toUpperCase()}
                </div>
                <div className="conversation-info">
                  <div className="contact-name">
                    {conversation.display_name || conversation.contact_mxid.split(':')[0].substring(1)}
                  </div>
                  <div className="conversation-status">
                    {conversation.has_messages ? (
                      <span className="has-messages">Recent messages</span>
                    ) : (
                      <span className="no-messages">Start conversation</span>
                    )}
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeContact(conversation.contact_mxid);
                  }}
                  className="remove-contact-btn"
                  title="Remove contact"
                >
                  ×
                </button>
              </div>
            ))
          ) : (
            <div className="no-conversations">
              <p>No contacts yet</p>
              <p>Search for users above to add them as contacts</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ContactsList;