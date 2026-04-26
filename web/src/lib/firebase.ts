import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, onIdTokenChanged, signInWithPopup, signOut, type NextOrObserver, type User, type UserCredential } from 'firebase/auth'
import { getStorage, ref, uploadBytes } from 'firebase/storage'

import { ENABLE_FIREBASE_AUTH } from '@/lib/config'

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
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

export function getFirebaseAuth() {
  const app = getFirebaseApp()
  return app ? getAuth(app) : null
}

export function listenToIdTokenChanges(nextOrObserver: NextOrObserver<User>) {
  const auth = getFirebaseAuth()
  if (!auth) {
    return () => undefined
  }
  return onIdTokenChanged(auth, nextOrObserver)
}

export async function signOutFromFirebase(): Promise<void> {
  const auth = getFirebaseAuth()
  if (!auth) {
    return
  }
  await signOut(auth)
}

export function getFirebaseStorageForPath(storagePath: string) {
  const app = getFirebaseApp()
  if (!app) {
    throw new Error('Firebase storage is not configured.')
  }
  const bucketAndPath = storagePath.replace(/^gs:\/\//, '')
  const slashIndex = bucketAndPath.indexOf('/')
  const bucket = slashIndex === -1 ? bucketAndPath : bucketAndPath.slice(0, slashIndex)
  const objectPath = slashIndex === -1 ? '' : bucketAndPath.slice(slashIndex + 1)
  return {
    storage: getStorage(app, `gs://${bucket}`),
    objectPath,
  }
}

export async function uploadFileToStoragePath(file: File, storagePath: string): Promise<void> {
  const { storage, objectPath } = getFirebaseStorageForPath(storagePath)
  if (!objectPath) {
    throw new Error('Upload registration did not return a valid storage object path.')
  }
  await uploadBytes(ref(storage, objectPath), file, {
    contentType: file.type || 'application/octet-stream',
  })
}
