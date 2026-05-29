import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import './index.css';
import { App } from './App';
import { BrandsListPage } from './pages/BrandsListPage';
import { BrandRegisterPage } from './pages/BrandRegisterPage';
import { BrandDetailPage } from './pages/BrandDetailPage';
import { AdDetailPage } from './pages/AdDetailPage';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<Navigate to="/brands" replace />} />
          <Route path="brands" element={<BrandsListPage />} />
          <Route path="brands/new" element={<BrandRegisterPage />} />
          <Route path="brands/:jobId" element={<BrandDetailPage />} />
          <Route path="brands/:jobId/ads/:adId" element={<AdDetailPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
