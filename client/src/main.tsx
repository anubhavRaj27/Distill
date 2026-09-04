import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import { Providers } from './app/Providers';

const root = document.getElementById('root');
if (!root) throw new Error('index.html is missing its #root element.');

createRoot(root).render(
  <StrictMode>
    <Providers>
      <App />
    </Providers>
  </StrictMode>,
);
