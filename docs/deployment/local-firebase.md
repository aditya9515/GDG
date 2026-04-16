# Local Firebase + Maps Wiring

## 1. Backend credentials

Use Application Default Credentials locally before starting the API:

```powershell
gcloud auth application-default login
```

Or set:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\service-account.json"
```

Then copy [`api/.env.example`](/D:/projects/GDG_1/api/.env.example) to `api/.env` and fill in:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET`
- `FIREBASE_TOKEN_CLOCK_SKEW_SECONDS=10`
- `REPOSITORY_BACKEND=firestore`
- `ALLOW_DEMO_AUTH=false`
- `GOOGLE_MAPS_API_KEY`
- `GEMINI_API_KEY`

## 2. Frontend env

Copy [`web/.env.local.example`](/D:/projects/GDG_1/web/.env.local.example) to `web/.env.local` and fill in:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_FIREBASE_*`
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
- `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`
- `NEXT_PUBLIC_ENABLE_DEMO_AUTH=false`

## 3. Bootstrap invited users

Seed the `users` collection before testing Google sign-in:

```powershell
npm run bootstrap:users
```

This upserts entries from [`seed/users.json`](/D:/projects/GDG_1/seed/users.json).

If you prefer calling `uv` directly, use module mode so Python treats `api/` as the import root:

```powershell
uv run --directory api --project . python -m scripts.bootstrap_users
```

The seed file includes local demo identities. For a real Google account, provision your email as an invited
operator:

```powershell
npm run provision:operator -- --email your-google-email@gmail.com --role INCIDENT_COORDINATOR
```

You can run this before or after your first Google sign-in. If Firebase Auth already has that account, the script
writes `users/{firebaseUid}`. If the account has not signed in yet, it writes an email invite placeholder; the backend
will bind that invite to the real Firebase UID on the first successful Google login.

Available roles:

- `INCIDENT_COORDINATOR`
- `MEDICAL_COORDINATOR`
- `LOGISTICS_LEAD`

## 4. Local run

Start the API:

```powershell
npm run dev:api
```

Start the web app:

```powershell
npm run dev:web
```

## 5. Expected behavior

- Google sign-in succeeds only for invited users present in Firestore `users`.
- If sign-in succeeds but the account is not provisioned, the login screen shows the email and the exact
  `npm run provision:operator` command to run.
- Local Firebase token verification allows a small clock skew. If you still see `Token used too early`, sync Windows
  time from **Settings -> Time & language -> Date & time -> Sync now** or run `w32tm /resync` from an elevated shell.
- Firestore client access is locked down; operational data flows through FastAPI.
- The map uses Google Maps JavaScript only when `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` is set.
- Geocoding uses the backend cache first and stores results in `geocode_cache`.
- Imports upload evidence to Firebase Storage first when Firebase Storage is configured in the web app.
