import React, { useState } from 'react';
import LoginForm from './LoginForm';
import RegisterForm from './RegisterForm';

const AuthModal = ({ isOpen, onClose }) => {
  const [currentForm, setCurrentForm] = useState('login'); // 'login' or 'register'

  if (!isOpen) return null;

  const handleSwitchToRegister = () => {
    setCurrentForm('register');
  };

  const handleSwitchToLogin = () => {
    setCurrentForm('login');
  };

  const handleClose = () => {
    setCurrentForm('login'); // Reset to login form
    onClose();
  };

  return (
    <div className="auth-modal-overlay" onClick={handleClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-modal-close" onClick={handleClose}>
          ×
        </button>
        
        {currentForm === 'login' && (
          <LoginForm
            onSwitchToRegister={handleSwitchToRegister}
            onClose={handleClose}
          />
        )}
        
        {currentForm === 'register' && (
          <RegisterForm
            onSwitchToLogin={handleSwitchToLogin}
            onClose={handleClose}
          />
        )}
      </div>
    </div>
  );
};

export default AuthModal;