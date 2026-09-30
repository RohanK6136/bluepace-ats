import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './AtsWorkspace.jsx'
import './index.css' // <--- Make sure this line is here!

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)