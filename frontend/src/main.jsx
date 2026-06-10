// Path: src/main.jsx
// File: main.jsx
// Created: 2026-03-29
// Purpose: Application entry point; mounts the React app with BrowserRouter into the DOM
// Caller: index.html (Vite entry point)
// Callees: react, react-dom, react-router-dom, App.jsx, styles/theme.css
// Data In: None
// Data Out: None (renders root React component)
// Last Modified: 2026-06-10

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/theme.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
