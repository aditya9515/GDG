import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, signInWithPopup, type UserCredential } from 'firebase/auth'

import { ENABLE_FIREBASE_AUTH } from '@/lib/config'

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
}

export function getFirebaseApp(): FirebaseApp | null {
  if (!ENABLE_FIREBASE_AUTH) {
    return null
  }

  return getApps()[0] ?? initializeApp(firebaseConfig)
}

export async function signInWithGoogle(): Promise<UserCredential> {
  const app = getFirebaseApp()
  if (!app) {
    throw new Error('Firebase auth is not configured.')
  }
  const auth = getAuth(app)
  return signInWithPopup(auth, new GoogleAuthProvider())
}
