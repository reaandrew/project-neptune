import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import './index.css';
import { App } from './App';
import { WelcomePage } from './pages/WelcomePage';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<WelcomePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
