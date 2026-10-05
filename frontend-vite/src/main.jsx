import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './AtsWorkspace.jsx'
import './index.css'

function removeStraySeparatorText(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let node = walker.nextNode();

  while (node) {
    const value = node.nodeValue || "";
    const normalized = value.replace(/\\r/g, "").replace(/\\n/g, "").trim();
    if (normalized === "|") {
      const withoutLiteralNewline = value.replace(/\\n/g, "").replace(/\\r/g, "").trim();
      if (withoutLiteralNewline === "|" || /^\\s*\\|\\s*$/.test(value)) {
        nodes.push(node);
      }
    }
    node = walker.nextNode();
  }

  nodes.forEach((textNode) => textNode.remove());
}

const rootElement = document.getElementById('root');
const root = ReactDOM.createRoot(rootElement)

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

const cleanup = () => removeStraySeparatorText(rootElement);
queueMicrotask(cleanup);
window.setTimeout(cleanup, 0);
window.setTimeout(cleanup, 100);
