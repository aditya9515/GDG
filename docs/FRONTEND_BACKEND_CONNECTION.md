# ReliefOps Frontend ↔ Backend Connection

This project has one browser-facing Next.js app and one private FastAPI backend. The frontend should call the backend only through `web/src/lib/api.ts`.

## Local Development

Run the API and web app in separate terminals:

```powershell
npm run dev:api
npm run dev:web
```

Required local frontend env in `web/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_ENABLE_DEMO_AUTH=false
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=...
NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=...
```

Required production-style backend env in `api/.env`:

```env
APP_ENV=development
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]
REPOSITORY_BACKEND=firestore
ALLOW_DEMO_AUTH=false
FIREBASE_PROJECT_ID=...
FIREBASE_STORAGE_BUCKET=...
GOOGLE_MAPS_API_KEY=...
GEMINI_API_KEY=...
AI_PROVIDER=gemini
GEMINI_ENABLED=true
GEMMA4_ENABLED=false
```

Optional local-only Gemma4/Ollama testing env:

```env
AI_PROVIDER=ollama
GEMINI_ENABLED=false
GEMMA4_ENABLED=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma4:e2b
```

Use Application Default Credentials locally for Firebase Admin and Firestore:

```powershell
gcloud auth application-default login
```

## Deployment

Frontend public values go in Firebase App Hosting / repo-root `apphosting.yaml`:

- `NEXT_PUBLIC_API_BASE_URL`: deployed FastAPI base URL.
- Firebase public web config values.
- `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`: browser key for Maps JavaScript API.

Backend private values go only in the backend runtime:

- Firebase project/storage config.
- Google Application Default Credentials or service account.
- `GOOGLE_MAPS_API_KEY`: private server key for Geocoding API and Routes API.
- Gemini provider settings. Keep `AI_PROVIDER=gemini`, `GEMINI_ENABLED=true`, and `GEMMA4_ENABLED=false` in production.
- `CORS_ORIGINS`: include the deployed App Hosting origin and local dev origins.

Do not put backend-only keys such as Gemini, Geocoding-only, or Routes-only keys into `NEXT_PUBLIC_*`.

## Runtime Contract

The frontend API helper sends:

- Firebase mode: `Authorization: Bearer <Firebase ID token>`.
- Demo mode: `X-Demo-User`.
- Organization scope: `X-Org-Id` whenever an active organization is selected.

Normal operator import flow:

```text
/imports -> POST /agent/graph1/run-file -> edit/remove drafts -> POST /agent/graph1/run/{id}/confirm
```

Normal dispatch flow:

```text
/dispatch -> POST /agent/graph2/batch-run -> edit/replan -> confirm selected case or full batch
```

The old `/ingestion-jobs` path is for admin/background imports, not the standard operator upload flow.

## Verification

Run:

```powershell
npm run test:api
npm --prefix web run test
npm --prefix web run build
npm --prefix web run test:e2e
```

In the app shell, open `System status` to verify:

- API health is reachable.
- Firebase session and active organization are valid.
- AI provider status is visible.
- Maps UI key is configured or the fallback map is active.
