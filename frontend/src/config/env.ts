// Base origin of the backend. Routes are absolute from here
// (e.g. `${apiBaseUrl}/api/v1/overview`).
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const appName = import.meta.env.VITE_APP_NAME ?? 'NEXUS';

export const appConfig = {
  apiBaseUrl,
  appName,
} as const;
