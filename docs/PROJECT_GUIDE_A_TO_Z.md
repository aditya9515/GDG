# ReliefOps AI Project Guide A to Z

## 1. Project Goal

ReliefOps AI is a maps-first smart resource allocation prototype for NGOs and emergency healthcare teams. The problem is simple but operationally painful: community information arrives as scattered field messages, CSV rosters, stock sheets, PDFs, images, and map notes. Coordinators need to quickly understand where incidents are, what resources are needed, which teams are available, and which response is closest and capable.

The product thesis is:

Turn scattered reports into geo-anchored operational records, then dispatch the right team and assets to the right place at the right time.

The judge demo path is:

1. A Google-authenticated user enters an NGO organization.
2. The operator pastes or uploads source data.
3. Graph 1 converts raw data into editable previews.
4. The operator edits, removes, or confirms data.
5. Confirmed records become incidents, teams, resources, info tokens, and Firestore vector records.
6. Graph 2 retrieves relevant context, asks follow-up questions if needed, and previews an assignment.
7. The operator confirms dispatch.
8. The system updates incident status, resource stock, team load, audit history, and CSV export.

## 2. User Roles

Every user signs in with Google. Google sign-in alone is not enough to see operational data; the user must belong to an organization.

Roles:

- `HOST`: Creates the organization, invites users, changes roles, removes users, and sees all organization members.
- `INCIDENT_COORDINATOR`: Handles triage and dispatch decisions.
- `MEDICAL_COORDINATOR`: Reviews healthcare emergencies.
- `LOGISTICS_LEAD`: Manages stock, vehicles, and supply movement.
- `VIEWER`: Can inspect operations but should not manage members.

The organization creator becomes `HOST`. A host can invite Gmail addresses. When an invited user signs in for the first time, the backend binds their Firebase UID to the existing email membership.

## 3. Organization Model

Core organization collections:

- `organizations`: NGO workspaces.
- `org_memberships`: User access per organization.
- `org_invites`: Pending or historical email invites.
- `users`: Firebase user profile and default organization.
- `audit_events`: Who changed what and when.

Operational collections are also organization-scoped:

- `incidents`
- `cases`
- `teams`
- `team_members`
- `resources`
- `dispatches`
- `info_tokens`
- `ingestion_jobs`
- `agent_runs`
- `vector_records`
- `duplicate_links`
- `eval_runs`
- `geocode_cache`

Every operational record should carry `org_id`. Backend routes require an active membership before reading or writing that organization's data.

## 4. Login and Invite Flow

1. User clicks Google sign-in.
2. Web app gets a Firebase ID token.
3. FastAPI verifies the token with Firebase Admin.
4. Backend finds or creates `users/{uid}`.
5. Backend checks `org_memberships` by Firebase UID and invited email.
6. If membership exists, `/me` returns organizations, memberships, role, active org, and host permissions.
7. If no membership exists, the frontend routes the user to create an organization or ask a host for an invite.

The demo button is hidden unless:

```env
NEXT_PUBLIC_ENABLE_DEMO_AUTH=true
```

Keep this false for real Firebase demos.

## 5. Frontend Pages

- `/login`: Google sign-in and optional seeded demo access.
- `/onboarding/create-organization`: Lets a signed-in user create an NGO and become host.
- `/organization`: Host-only member dashboard with invite, role change, pending invites, and remove actions.
- `/command-center`: Map-first incident board and quick intake.
- `/imports`: Graph 1 review workspace for preview, prompt edit, remove, and confirm.
- `/incidents/[id]`: Incident detail, location, duplicate evidence, recommendations, and dispatch action.
- `/dispatch`: Active and completed dispatches.
- `/teams`: Team capability, availability, and current load.
- `/resources`: Inventory, stock, reservations, and map context.
- `/analytics`: Backlog, confidence, map coverage, and latest evaluation.

The sidebar includes an organization selector. API calls include the selected organization as `X-Org-Id`.

## 6. Backend Route Groups

- `/me`: Current user, memberships, organizations, auth mode, and active org.
- `/organizations`: Host organization creation and member management.
- `/incidents` and `/cases`: Incident lifecycle.
- `/teams`, `/resources`, `/dispatches`: Operational reads.
- `/uploads/register`: Storage-backed upload session placeholder.
- `/ingestion-jobs`: Import job tracking.
- `/agent/graph1/*`: Intake preview graph.
- `/agent/graph2/*`: Assignment execution graph.
- `/agent/graph3/*`: Combined demo graph entrypoint.
- `/agent/runs/{run_id}`: Graph run inspection.
- `/agent/runs/{run_id}/export.csv`: CSV export for run previews and committed records.
- `/dashboard/summary`: Organization-scoped metrics.

All operational routes are backend-first. The frontend uses Firebase directly only for sign-in and public client SDK setup.

## 7. Graph 1: Source to Operational Records

Graph 1 is named `source_to_operational_records_graph`.

Flow:

```text
source_loader_node
-> docling_parse_node
-> document_normalizer_node
-> prune_redact_node
-> gemini_draft_node
-> geocode_node
-> preview_node
```

Inputs:

- Manual text.
- CSV rows.
- PDF files.
- Images and screenshots.
- DOCX/XLSX when the local parser supports them.
- Map pins.
- Geodatabase-derived rows.
- Existing evidence IDs.

Docling runs before Gemini for files. Its job is to convert PDFs, images, tables, and documents into clean Markdown/JSON chunks with source references. Gemini receives cleaned chunks, not huge raw documents.

Manual text can skip heavy Docling parsing, but still goes through the same graph preview flow.

Operator actions:

- Confirm draft.
- Edit draft with a prompt.
- Add new data with a prompt.
- Remove draft data before commit.

Only confirmed drafts write to Firestore operational collections and vector records.

## 8. Graph 2: Dispatch Assignment

Graph 2 is named `dispatch_assignment_graph`.

Flow:

```text
retrieve_context_node
-> supervisor_node
-> planning_node
-> maps_eta_node
-> assignment_preview_node
-> confirmation_node
```

The supervisor pauses when information is missing or unsafe:

- Unknown or ambiguous location.
- Conflicting incident details.
- No valid certification.
- Depleted resource.
- Expired stock.
- Unavailable team.
- Duplicate incident.
- Route failure.
- Conflicting severity.

When paused, the run status becomes `WAITING_FOR_USER`. The UI shows questions. The operator answers through:

```text
POST /agent/graph2/run/{run_id}/resume
```

The backend writes answers into graph state, marks `needs_user_input=false`, and reevaluates.

## 9. Graph 3: Full Demo Flow

Graph 3 is named `intake_to_dispatch_graph`.

It combines Graph 1 and Graph 2 for the judge demo. V1 starts with Graph 1 and launches Graph 2 after records are confirmed. This keeps the operator in control: nothing becomes an operational dispatch until a human confirms.

## 10. Docling Role

Docling is the document preparation layer. It should:

- Extract Markdown from PDFs/docs.
- Extract tables.
- Preserve page and table references.
- Run OCR for scanned files/images.
- Support English and Hindi.
- Return parse warnings when extraction is weak.

If Docling is unavailable or fails, the backend uses a safe fallback parser and records warnings. This keeps demos working while still documenting that full OCR needs Docling runtime dependencies.

## 11. Gemini Role

Gemini is the semantic extraction and reasoning layer. It should:

- Convert cleaned Docling chunks into incident, team, resource, dispatch-note, and info-token drafts.
- Explain missing information.
- Reevaluate one draft after an operator prompt.
- Help identify duplicate or conflicting data.
- Produce structured records matching backend schemas.

For local tests, the backend can use deterministic fallbacks so tests do not require live Gemini calls.

## 12. Info Tokens

`InfoToken` is the normalized evidence unit. Raw input can be messy, but tokens should be small and useful.

Token types:

- `NEED`
- `TEAM_CAPABILITY`
- `RESOURCE_CAPABILITY`
- `LOCATION_HINT`
- `AVAILABILITY_UPDATE`

Case-side tokens extract need category, urgency cues, quantities, time window, hazard type, location candidates, and source confidence.

Team/resource-side tokens extract capability tags, certifications, supported resource types, operating area, stock, and availability notes.

## 13. Firestore Vector Records

V1 stores embeddings in Firestore collection `vector_records`.

Fields:

- `org_id`
- `record_type`
- `record_id`
- `token_id`
- `embedding`
- `text`
- `metadata`
- `source_refs`
- `status`
- `version`
- `deleted_at`

The backend performs cosine search in the selected organization only. Deleted vectors are excluded. This avoids a separate vector database for V1.

## 14. Maps Role

Maps are used for:

- Geocoding text locations.
- Showing incidents, teams, and resources.
- ETA and route-aware recommendations.
- Manual map-pin confirmation for weak locations.

If location confidence is `UNKNOWN`, dispatch confirmation should be blocked until the operator confirms location.

## 15. Prompt Edit, Add, and Remove

Prompt edits never directly mutate confirmed records. They update draft state first.

Examples:

- "Correct location to Shantinagar bridge, Patna."
- "Add N95 masks because smoke exposure is reported."
- "Remove the duplicate food draft."

Confirmed data is soft-deleted, not hard-deleted. Soft deletion writes `deleted_at`, `deleted_by`, and an audit event.

## 16. Test Data

Use `test_inputs/organization_test_1` for happy-path organization testing:

- `incidents.csv`
- `teams.csv`
- `resources.csv`
- `manual_intake_cases.txt`
- `operator_prompts.txt`
- `expected_preview.json`

Use `test_inputs/organization_test_2` for missing-location, duplicate, certification, depleted stock, and Hindi/English cases.

Use `test_inputs/organization_test_3` for multi-organization isolation and host permission scenarios.

Mocked Docling output lives at:

- `test_inputs/sample_assessment.docling.md`
- `test_inputs/sample_assessment.docling.json`
- `test_inputs/warehouse_photo.docling.json`

## 17. Current Code Layout

Root folders:

- `api/`: FastAPI backend, repositories, services, tests, and scripts.
- `web/`: Next.js App Router frontend.
- `seed/`: Firestore seed data for demo users, organizations, memberships, incidents, teams, and resources.
- `test_inputs/`: Human-readable sample files for organization workflow testing.
- `eval/`: Golden-case evaluation harness.
- `docs/`: Project guides, deployment notes, and schema references.

Important backend files:

- `api/app/main.py`: FastAPI app registration.
- `api/app/core/security.py`: Firebase token verification, demo auth gate, org membership binding, active organization enforcement.
- `api/app/models/domain.py`: Shared Pydantic domain contracts.
- `api/app/repositories/firestore.py`: Live Firestore implementation.
- `api/app/repositories/memory.py`: Local test/demo implementation.
- `api/app/api/routes/organizations.py`: Host organization and membership APIs.
- `api/app/api/routes/agents.py`: Graph 1, Graph 2, Graph 3 run/edit/resume/confirm APIs.
- `api/app/services/agent_graphs.py`: Graph orchestration service.
- `api/app/services/docling_parser.py`: Docling-first parsing adapter with safe fallback.
- `api/app/services/vectors.py`: Gemini embedding adapter with deterministic fallback.

Important frontend files:

- `web/src/components/providers/auth-provider.tsx`: Firebase/demo auth bootstrap, `/me` hydration, org switcher state.
- `web/src/components/layout/app-shell.tsx`: Operations shell, sidebar, org selector, host-only navigation.
- `web/src/app/(app)/onboarding/create-organization/page.tsx`: First organization creation.
- `web/src/app/(app)/organization/page.tsx`: Host member management.
- `web/src/app/(app)/imports/page.tsx`: Graph 1 preview/edit/remove/confirm UI.
- `web/src/lib/api.ts`: Backend client with Firebase token and `X-Org-Id`.
- `web/src/lib/types.ts`: TypeScript mirror of the shared contracts.

## 18. Local Development

Start API:

```powershell
npm run dev:api
```

Start web:

```powershell
npm run dev:web
```

Run tests:

```powershell
npm run test
```

Build web:

```powershell
npm --prefix web run build
```

## 19. Seeding and Provisioning

Bootstrap users, organizations, memberships, and invites:

```powershell
npm run bootstrap:users
```

Provision a real Google account:

```powershell
npm run provision:operator -- --email your@gmail.com --role INCIDENT_COORDINATOR
```

Provision a real Google account directly into an organization:

```powershell
npm run provision:operator -- --email your@gmail.com --org-id org-demo-relief --role INCIDENT_COORDINATOR
```

Create a new organization from the command line and make the operator host:

```powershell
npm run provision:operator -- --email host@gmail.com --org-name "District Relief NGO" --make-host
```

If the Google account has never signed in, the script creates an email invite placeholder. After first Google sign-in, the backend binds the real Firebase UID to the membership.

## 20. Environment Variables

API:

- `REPOSITORY_BACKEND=firestore` to use live Firestore.
- `FIREBASE_PROJECT_ID` for Firebase Admin and Firestore.
- `FIRESTORE_DATABASE=(default)` unless you configured another database.
- `ALLOW_DEMO_AUTH=false` outside local demos.
- `GEMINI_API_KEY` for structured extraction and embeddings.
- `GOOGLE_MAPS_API_KEY` for backend geocoding/routing.
- `FIREBASE_AUTH_CLOCK_SKEW_SECONDS=10` can smooth small local clock drift.

Web:

- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
- `NEXT_PUBLIC_FIREBASE_APP_ID`
- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`
- `NEXT_PUBLIC_ENABLE_DEMO_AUTH=true` only for local demo mode.

Never commit live `.env` secrets.

## 21. Organization Isolation Rules

The backend treats `X-Org-Id` as the selected workspace, but it does not trust it blindly.

For every protected request:

- Firebase token identifies the user.
- Backend loads active memberships by UID or invited email.
- Backend verifies the requested `X-Org-Id` is an active membership.
- Operational reads/writes are filtered by `org_id`.
- Graph runs and vector searches reject cross-organization access.

If a host removes a member while that member is active, subsequent protected API calls fail because the membership is no longer active. The frontend should refresh `/me` and route that user away from organization pages.

## 22. Graph Run Lifecycle

Graph 1 statuses:

- `RUNNING`: Accepted request and started parsing.
- `WAITING_FOR_CONFIRMATION`: Drafts are ready; operator can edit, remove, or confirm.
- `COMMITTED`: Confirmed drafts were written to operational collections and vector records.
- `FAILED`: Parsing or commit failed.

Graph 2 statuses:

- `WAITING_FOR_USER`: Supervisor needs missing information such as exact location, certification, or resource clarification.
- `WAITING_FOR_CONFIRMATION`: Dispatch preview is ready.
- `COMMITTED`: Dispatch has been confirmed.

Graph run documents live in `agent_runs`. They are intentionally visible through APIs so the UI can poll and recover after refreshes.

## 23. Adding New Test Data

For a new organization test:

1. Create a new folder under `test_inputs/organization_test_N`.
2. Add `incidents.csv`, `teams.csv`, and `resources.csv` if the scenario needs structured imports.
3. Add `manual_intake_cases.txt` for copy-paste reports.
4. Add `operator_prompts.txt` with the prompts you expect the operator to try.
5. Add `expected_preview.json` for the draft cards Graph 1 should produce.

Keep rows small and realistic. The best tests include one happy path and one sharp edge case, such as a missing location, duplicate incident, depleted stock, or invalid certification.

## 24. Debugging Checklist

Auth:

- Check Firebase env vars.
- Check system clock if token says "used too early."
- Check `/me` response.
- Check `org_memberships` for the signed-in email.

Firestore:

- Verify `REPOSITORY_BACKEND=firestore`.
- Verify Application Default Credentials.
- Verify rules block unsafe client writes.
- Verify every operational document has `org_id`.

Maps:

- Check browser Maps key for UI.
- Check server Maps key for geocoding/routes.
- Watch quota and cache geocodes.

Gemini:

- Check `GEMINI_API_KEY`.
- Use heuristic fallback in tests.
- Log schema validation failures.

Docling:

- Confirm package/runtime dependencies.
- Use mocked Docling outputs in tests.
- Fallback parser should produce warnings, not crash the graph.

Graph runs:

- Check `agent_runs/{run_id}`.
- Inspect `status`, `drafts`, `user_questions`, and `error_message`.
- Confirm `X-Org-Id` is present.

## 25. Edge Cases Covered by Design

Host/member:

- Host removes a member while active: backend rejects future org-scoped requests.
- User belongs to multiple orgs: frontend org selector sets `X-Org-Id`.
- Invited Gmail logs in first time: backend binds email membership to Firebase UID.
- Removed user attempts old org access: membership status blocks access.
- Non-host attempts invite/remove: organization routes return `403`.

Ingestion:

- Corrupt or unsupported files should create parse warnings, not crash the graph.
- Broken CSV and missing headers should stop at preview/review.
- Hindi/English text is preserved through the parser and passed to Gemini/fallback extraction.
- Low-signal text is pruned before draft generation.

Data:

- Missing location blocks safe dispatch and asks the operator for clarification.
- Zero quantity, expired stock, and unavailable teams should fail supervisor checks.
- PII should be minimized in tokens and logs.

Vector:

- Retrieval is always scoped by `org_id`.
- Deleted vectors are excluded.
- Prompt-added data is vectorized only after confirmation.

## 26. Known V1 Boundaries

The current implementation is a working architecture scaffold optimized for the GDG demo path. It deliberately avoids overbuilding.

Implemented now:

- Host organizations and invited Gmail access.
- Organization-scoped backend APIs.
- Demo/local and Firebase auth modes.
- Docling-first parser adapter with safe fallback.
- Graph 1 preview/edit/remove/confirm workflow.
- Graph 2 missing-info pause and assignment preview workflow.
- Firestore-backed vector records with backend cosine search.
- Test fixtures for organization, edge-case, and isolation scenarios.

Still intentionally lightweight:

- Real Docling runtime may need local/system OCR dependencies for scanned PDFs.
- Graph services are explicit FastAPI checkpointed workflows; deeper LangGraph package integration can be swapped in later without changing public endpoints.
- File upload processing has the evidence/job model in place, but the richest document/table extraction mapping is still a stretch enhancement.
- Route matrix optimization is capped and should be expanded only after cost testing.

## 27. Future Changes

- Replace backend cosine search with native Firestore vector indexes when ready.
- Add ownership transfer for hosts.
- Add Drive/WhatsApp/email connectors.
- Add real geodatabase upload parsing.
- Add hard-delete admin tool with strict audit requirements.
- Add richer Docling table-to-resource mapping.
- Add route matrix optimization for many teams.
