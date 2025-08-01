import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';

const UserProfile = ({ isOpen, onClose }) => {
  const { user, logout, updateProfile } = useAuth();
  const [editing, setEditing] = useState(false);
  const [formData, setFormData] = useState({
    displayName: user?.display_name || '',
    avatarUrl: user?.avatar_url || ''
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  if (!isOpen || !user) return null;

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    });
  };

  const handleSave = async () => {
    setLoading(true);
    setError('');
    setSuccess('');

    const result = await updateProfile(formData.displayName, formData.avatarUrl);
    
    if (result.success) {
      setSuccess('Profil mis à jour avec succès !');
      setEditing(false);
      setTimeout(() => setSuccess(''), 3000);
    } else {
      setError(result.error);
    }
    
    setLoading(false);
  };

  const handleCancel = () => {
    setFormData({
      displayName: user.display_name || '',
      avatarUrl: user.avatar_url || ''
    });
    setEditing(false);
    setError('');
    setSuccess('');
  };

  const handleLogout = () => {
    logout();
    onClose();
  };

  return (
    <div className="profile-modal-overlay" onClick={onClose}>
      <div className="profile-modal" onClick={(e) => e.stopPropagation()}>
        <div className="profile-header">
          <h2>Profil utilisateur</h2>
          <button className="profile-close" onClick={onClose}>×</button>
        </div>

        <div className="profile-content">
          <div className="profile-info">
            <div className="profile-avatar">
              {user.avatar_url ? (
                <img src={user.avatar_url} alt="Avatar" />
              ) : (
                <div className="avatar-placeholder">
                  {user.display_name?.charAt(0)?.toUpperCase() || user.localpart?.charAt(0)?.toUpperCase()}
                </div>
              )}
            </div>
            
            <div className="profile-details">
              <div className="profile-field">
                <label>ID Matrix:</label>
                <span className="matrix-id">{user.mxid}</span>
              </div>
              
              <div className="profile-field">
                <label>Email:</label>
                <span>{user.email}</span>
              </div>
              
              <div className="profile-field">
                <label>Membre depuis:</label>
                <span>{new Date(user.created_at).toLocaleDateString('fr-FR')}</span>
              </div>
            </div>
          </div>

          {editing ? (
            <div className="profile-edit">
              <div className="form-group">
                <label htmlFor="displayName">Nom d'affichage:</label>
                <input
                  type="text"
                  id="displayName"
                  name="displayName"
                  value={formData.displayName}
                  onChange={handleChange}
                  className="form-input"
                  placeholder="Votre nom d'affichage"
                />
              </div>

              <div className="form-group">
                <label htmlFor="avatarUrl">URL de l'avatar:</label>
                <input
                  type="url"
                  id="avatarUrl"
                  name="avatarUrl"
                  value={formData.avatarUrl}
                  onChange={handleChange}
                  className="form-input"
                  placeholder="https://exemple.com/avatar.jpg"
                />
              </div>

              {error && <div className="error-message">{error}</div>}
              {success && <div className="success-message">{success}</div>}

              <div className="profile-actions">
                <button
                  onClick={handleSave}
                  disabled={loading}
                  className="profile-button primary"
                >
                  {loading ? 'Sauvegarde...' : 'Sauvegarder'}
                </button>
                <button
                  onClick={handleCancel}
                  className="profile-button secondary"
                >
                  Annuler
                </button>
              </div>
            </div>
          ) : (
            <div className="profile-view">
              <div className="profile-field">
                <label>Nom d'affichage:</label>
                <span>{user.display_name || 'Non défini'}</span>
              </div>

              <div className="profile-actions">
                <button
                  onClick={() => setEditing(true)}
                  className="profile-button primary"
                >
                  Modifier le profil
                </button>
                <button
                  onClick={handleLogout}
                  className="profile-button danger"
                >
                  Se déconnecter
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default UserProfile;