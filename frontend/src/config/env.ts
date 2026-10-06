const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1'
const appName = import.meta.env.VITE_APP_NAME ?? 'NEXUS'

export const appConfig = {
  apiBaseUrl,
  appName,
} as const
