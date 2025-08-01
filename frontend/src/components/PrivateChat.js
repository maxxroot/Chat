import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const PrivateChat = ({ contact }) => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (contact) {
      loadMessages();
    }
  }, [contact]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const loadMessages = async () => {
    if (!contact?.contact_mxid) return;

    setLoading(true);
    try {
      const response = await axios.get(
        `${API}/messages/private/${encodeURIComponent(contact.contact_mxid)}?limit=50`
      );
      setMessages(response.data.messages || []);
    } catch (error) {
      console.error('Failed to load messages:', error);
      setMessages([]);
    } finally {
      setLoading(false);
    }
  };

  const sendMessage = async () => {
    if (!newMessage.trim() || !contact?.contact_mxid || sending) return;

    const messageText = newMessage.trim();
    setNewMessage('');
    setSending(true);

    try {
      const response = await axios.post(`${API}/messages/private/send`, {
        recipient_mxid: contact.contact_mxid,
        message: messageText
      });

      // Add the message to local state immediately for better UX
      const newMsg = {
        message_id: response.data.message_id,
        sender_mxid: user.mxid,
        recipient_mxid: contact.contact_mxid,
        content: messageText,
        timestamp: response.data.timestamp,
        is_own_message: true
      };

      setMessages(prev => [...prev, newMsg]);
    } catch (error) {
      console.error('Failed to send message:', error);
      alert('Failed to send message: ' + (error.response?.data?.detail || error.message));
      // Restore the message text on failure
      setNewMessage(messageText);
    } finally {
      setSending(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (!contact) {
    return (
      <div className="private-chat-placeholder">
        <div className="placeholder-content">
          <h3>Select a contact to start chatting</h3>
          <p>Your messages are end-to-end encrypted</p>
          <div className="encryption-info">
            <div className="encryption-icon">🔒</div>
            <div className="encryption-text">
              <h4>End-to-End Encryption</h4>
              <p>Only you and your contact can read these messages</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="private-chat">
      {/* Chat Header */}
      <div className="private-chat-header">
        <div className="contact-info">
          <div className="contact-avatar">
            {contact.contact_avatar_url ? (
              <img src={contact.contact_avatar_url} alt="Avatar" />
            ) : (
              <div className="avatar-placeholder">
                {contact.display_name?.charAt(0)?.toUpperCase() || 
                 contact.contact_mxid?.charAt(1)?.toUpperCase()}
              </div>
            )}
          </div>
          <div className="contact-details">
            <h3>{contact.display_name || contact.contact_mxid?.split(':')[0]?.substring(1)}</h3>
            <div className="contact-mxid">{contact.contact_mxid}</div>
          </div>
        </div>
        <div className="encryption-indicator">
          <div className="encryption-icon">🔒</div>
          <span>Encrypted</span>
        </div>
      </div>

      {/* Messages Container */}
      <div className="private-messages-container">
        {loading ? (
          <div className="loading-messages">
            <div className="loading-spinner"></div>
            <p>Loading messages...</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="no-messages-private">
            <div className="welcome-message">
              <h4>Start your conversation with {contact.display_name || contact.contact_mxid?.split(':')[0]?.substring(1)}</h4>
              <p>This is a private, end-to-end encrypted conversation.</p>
              <div className="first-message-hint">
                <div className="encryption-shield">🛡️</div>
                <p>Your messages are secured with RSA+AES encryption</p>
              </div>
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <div
                key={message.message_id}
                className={`private-message ${message.is_own_message ? 'own-message' : 'other-message'}`}
              >
                <div className="message-content">
                  <div className="message-text">{message.content}</div>
                  <div className="message-timestamp">
                    {new Date(message.timestamp).toLocaleTimeString([], { 
                      hour: '2-digit', 
                      minute: '2-digit' 
                    })}
                  </div>
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Message Input */}
      <div className="private-message-input-container">
        <div className="message-input-wrapper">
          <input
            type="text"
            placeholder={`Message ${contact.display_name || contact.contact_mxid?.split(':')[0]?.substring(1)}...`}
            value={newMessage}
            onChange={(e) => setNewMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            className="private-message-input"
            disabled={sending}
          />
          <button
            onClick={sendMessage}
            disabled={!newMessage.trim() || sending}
            className="private-send-btn"
          >
            {sending ? '...' : 'Send'}
          </button>
        </div>
        <div className="encryption-notice">
          🔒 Messages are end-to-end encrypted
        </div>
      </div>
    </div>
  );
};

export default PrivateChat;