export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000'
export const ENABLE_FIREBASE_AUTH = Boolean(
  process.env.NEXT_PUBLIC_FIREBASE_API_KEY &&
    process.env.NEXT_PUBLIC_FIREBASE_APP_ID &&
    process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN &&
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
)
export const ENABLE_DEMO_AUTH =
  process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH === 'true' ||
  (!ENABLE_FIREBASE_AUTH && process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH !== 'false')
export const GOOGLE_MAPS_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? ''
export const ENABLE_GOOGLE_MAPS_UI = GOOGLE_MAPS_API_KEY.length > 0
export const ENABLE_STORAGE_UPLOADS = Boolean(
  ENABLE_FIREBASE_AUTH && process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
)
