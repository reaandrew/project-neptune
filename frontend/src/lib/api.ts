// All calls go through the BFF, which transforms the
// .andrewreaassociates.com `auth_token` cookie into the Authorization
// header upstream. `credentials: 'include'` is required so the browser
// actually sends the cookie cross-subdomain.
const BFF_BASE = 'https://bff.projectneptune.andrewreaassociates.com';

// ara login page. We bounce users here with ?returnTo so the cookie
// is set before they come back.
const AUTH_LOGIN_URL = 'https://andrewreaassociates.com/admin.html';

export class UnauthorizedError extends Error {
  constructor() {
    super('unauthorized');
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BFF_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      ...(init?.headers ?? {}),
      'Accept': 'application/json',
    },
  });
  if (res.status === 401 || res.status === 403) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${res.status}: ${body || res.statusText}`);
  }
  return (await res.json()) as T;
}

export interface MessageResponse {
  message: string;
}

export function getMessage(): Promise<MessageResponse> {
  return request<MessageResponse>('/message');
}

// ---- Brand-guidelines jobs ----

export type BrandJobStatus = 'pending' | 'running' | 'done' | 'error';

export interface BrandJob {
  jobId: string;
  status: BrandJobStatus;
  url?: string;
  pdfUrl?: string;
  yamlUrl?: string;
  jsonUrl?: string;
  error?: string;
  createdAt?: string;
  completedAt?: string;
}

export interface CreateBrandJobResponse {
  jobId: string;
  cached?: boolean;
}

export function createBrandJob(
  url: string,
  opts: { force?: boolean } = {},
): Promise<CreateBrandJobResponse> {
  return request<CreateBrandJobResponse>('/brand-jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, force: opts.force ?? false }),
  });
}

export function getBrandJob(jobId: string): Promise<BrandJob> {
  return request<BrandJob>(`/brand-jobs/${encodeURIComponent(jobId)}`);
}

export interface BrandJobSummary {
  jobId: string;
  url?: string;
  status: BrandJobStatus;
  createdAt?: string;
}

export function listBrandJobs(): Promise<{ jobs: BrandJobSummary[] }> {
  return request<{ jobs: BrandJobSummary[] }>('/brand-jobs');
}

// ---- Ads ----

export type AdJobStatus = 'pending' | 'running' | 'done' | 'error';

export interface AdJob {
  adId: string;
  brandJobId?: string;
  status: AdJobStatus;
  headline?: string;
  body?: string;
  cta?: string;
  imageUrl?: string;
  error?: string;
  createdAt?: string;
  completedAt?: string;
}

export interface CreateAdInput {
  brandJobId: string;
  headline?: string;
  body?: string;
  cta?: string;
  sampleAdUrl?: string;
}

export function createAdJob(input: CreateAdInput): Promise<{ adId: string }> {
  return request<{ adId: string }>('/ads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export function getAdJob(adId: string): Promise<AdJob> {
  return request<AdJob>(`/ads/${encodeURIComponent(adId)}`);
}

export interface AdSummary {
  adId: string;
  brandJobId?: string;
  status: AdJobStatus;
  headline?: string;
  createdAt?: string;
}

export function listAds(brandJobId?: string): Promise<{ ads: AdSummary[] }> {
  const qs = brandJobId ? `?brandJobId=${encodeURIComponent(brandJobId)}` : '';
  return request<{ ads: AdSummary[] }>(`/ads${qs}`);
}


export function redirectToLogin(): void {
  const returnTo = window.location.href;
  const url = new URL(AUTH_LOGIN_URL);
  url.searchParams.set('returnTo', returnTo);
  window.location.replace(url.toString());
}
