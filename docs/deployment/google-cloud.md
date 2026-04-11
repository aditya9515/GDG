# Google Cloud Deployment Notes

## Required Tooling

The local machine currently has Docker installed, but not the `gcloud` or `firebase` CLIs. Install both before deployment work:

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
- [Firebase CLI](https://firebase.google.com/docs/cli)

## Backend

1. Create a Google Cloud project and enable Cloud Run, Firestore, Secret Manager, and Gemini API access.
2. Store `GEMINI_API_KEY` and `GOOGLE_MAPS_API_KEY` in Secret Manager.
3. Build and deploy the FastAPI container from [`api/Dockerfile`](/D:/projects/GDG_1/api/Dockerfile).
4. Set runtime environment values:
   - `REPOSITORY_BACKEND=firestore`
   - `FIREBASE_PROJECT_ID=<project-id>`
   - `EXTRACTION_PROVIDER=gemini`

## Frontend

1. Configure Firebase Auth, Firestore, and App Hosting in the same project.
2. Update [`web/apphosting.yaml`](/D:/projects/GDG_1/web/apphosting.yaml) with the Cloud Run URL and demo-auth policy.
3. Add the Firebase public env vars in App Hosting.
4. Disable demo auth in production by setting `NEXT_PUBLIC_ENABLE_DEMO_AUTH=false`.

## Secrets And Safety

- Keep live credentials in Secret Manager, not repo `.env` files.
- Leave `ALLOW_DEMO_AUTH=false` in production if you do not want header-based test access.
- Review Cloud Run ingress and Auth settings before sharing the judge URL.
