import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import './index.css';
import { App } from './App';
import { BrandGuidelinesPage } from './pages/BrandGuidelinesPage';
import { BrandJobDetailPage } from './pages/BrandJobDetailPage';
import { WelcomePage } from './pages/WelcomePage';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<WelcomePage />} />
          <Route path="brand" element={<BrandGuidelinesPage />} />
          <Route path="brand/:jobId" element={<BrandJobDetailPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
