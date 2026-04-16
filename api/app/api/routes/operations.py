from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.dependencies import (
    get_extraction_service,
    get_geocoding_service,
    get_repository,
    get_scoring_service,
    get_storage_bridge_service,
    get_token_service,
)
from app.core.config import get_settings
from app.core.security import get_current_org_user, get_current_user
from app.models.domain import (
    AuthSessionResponse,
    CaseEvent,
    DispatchListResponse,
    EvidenceStatus,
    GeoPoint,
    IngestionJob,
    IngestionJobsResponse,
    IngestionKind,
    IngestionStatus,
    InfoTokenType,
    LocationConfidence,
    ResourcesResponse,
    Team,
    TeamsResponse,
    UploadRegistrationRequest,
    UploadRegistrationResponse,
    UserContext,
    VolunteersResponse,
    ResourceInventory,
)

router = APIRouter(tags=["operations"])


@router.get("/me", response_model=AuthSessionResponse)
def get_session_profile(actor: UserContext = Depends(get_current_user)):
    repository = get_repository()
    settings = get_settings()
    profile = repository.get_user_profile(actor.uid)
    organizations, memberships = repository.list_organizations_for_user(actor.uid, actor.email)
    return AuthSessionResponse(
        uid=actor.uid,
        email=actor.email,
        role=actor.role,
        enabled=profile.enabled if profile else True,
        team_scope=profile.team_scope if profile else actor.team_scope,
        auth_mode="demo" if settings.resolved_demo_auth and actor.uid.startswith("demo-") else "firebase",
        repository_backend=settings.resolved_repository_backend,
        organizations=organizations,
        memberships=memberships,
        default_org_id=profile.default_org_id if profile else (memberships[0].org_id if memberships else None),
        active_org_id=actor.active_org_id,
        is_host=any(item.role == "HOST" for item in memberships),
    )


@router.get("/teams", response_model=TeamsResponse)
def list_teams(actor: UserContext = Depends(get_current_org_user)):
    return TeamsResponse(items=[item for item in get_repository().list_teams() if item.org_id in {None, actor.active_org_id}])


@router.get("/volunteers", response_model=VolunteersResponse)
def list_volunteers(actor: UserContext = Depends(get_current_org_user)):
    return VolunteersResponse(items=[item for item in get_repository().list_volunteers() if item.org_id in {None, actor.active_org_id}])


@router.get("/resources", response_model=ResourcesResponse)
def list_resources(actor: UserContext = Depends(get_current_org_user)):
    return ResourcesResponse(items=[item for item in get_repository().list_resources() if item.org_id in {None, actor.active_org_id}])


@router.get("/dispatches", response_model=DispatchListResponse)
def list_dispatches(actor: UserContext = Depends(get_current_org_user)):
    return DispatchListResponse(items=[item for item in get_repository().list_assignments() if item.org_id in {None, actor.active_org_id}])


@router.post("/uploads/register", response_model=UploadRegistrationResponse)
def register_upload(
    payload: UploadRegistrationRequest,
    actor: UserContext = Depends(get_current_org_user),
):
    return get_repository().register_upload(payload, actor)


@router.get("/ingestion-jobs", response_model=IngestionJobsResponse)
def list_ingestion_jobs(actor: UserContext = Depends(get_current_org_user)):
    return IngestionJobsResponse(items=[item for item in get_repository().list_ingestion_jobs() if item.org_id in {None, actor.active_org_id}])


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJob)
def get_ingestion_job(job_id: str, actor: UserContext = Depends(get_current_org_user)):
    job = get_repository().get_ingestion_job(job_id)
    if job.org_id not in {None, actor.active_org_id}:
        raise HTTPException(status_code=403, detail="Ingestion job belongs to another organization.")
    return job


@router.post("/ingestion-jobs", response_model=IngestionJob)
async def create_ingestion_job(
    kind: IngestionKind = Form(...),
    target: str = Form(...),
    linked_case_id: str | None = Form(default=None),
    evidence_id: str | None = Form(default=None),
    storage_path: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    content_type: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    actor: UserContext = Depends(get_current_org_user),
):
    repository = get_repository()
    extractor = get_extraction_service()
    geocoder = get_geocoding_service()
    scorer = get_scoring_service()
    storage_bridge = get_storage_bridge_service()
    token_service = get_token_service()

    job = IngestionJob(
        job_id=f"job-{uuid.uuid4().hex[:10]}",
        org_id=actor.active_org_id,
        kind=kind,
        target=target,
        filename=filename or (file.filename if file else "upload.bin"),
        status=IngestionStatus.PROCESSING,
        created_by=actor.uid,
    )
    repository.create_ingestion_job(job)

    try:
        if file is not None:
            content = await file.read()
            resolved_filename = file.filename or filename or "upload.bin"
            resolved_content_type = file.content_type or content_type or "application/octet-stream"
        elif storage_path:
            content = storage_bridge.download_bytes(storage_path)
            resolved_filename = filename or storage_path.rsplit("/", maxsplit=1)[-1]
            resolved_content_type = content_type or "application/octet-stream"
        else:
            raise ValueError("Provide either a multipart file or a registered storage_path for ingestion.")

        if kind == IngestionKind.CSV:
            text = content.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            job.row_count = len(rows)
            if target == "incidents":
                for row in rows:
                    raw_input = row.get("raw_input") or row.get("summary") or " | ".join(
                        value.strip() for value in row.values() if value and value.strip()
                    )
                    case = repository.create_case(raw_input, "CSV_IMPORT", actor)
                    extraction = extractor.extract(raw_input)
                    repository.save_extraction(case.case_id, extraction, status="EXTRACTED")
                    geo = await geocoder.geocode(row.get("location_text") or extraction.location_text)
                    if geo is not None:
                        repository.update_case_location(
                            case.case_id,
                            row.get("location_text") or extraction.location_text,
                            geo.lat,
                            geo.lng,
                            LocationConfidence.APPROXIMATE,
                        )
                    rationale = scorer.score(extraction)
                    repository.save_scoring(case.case_id, rationale.final_score, rationale, rationale.final_urgency)
                    repository.save_info_tokens(case.case_id, token_service.from_incident(repository.get_case(case.case_id), extraction))
                    repository.record_event(
                        CaseEvent(
                            event_id=f"evt-{uuid.uuid4().hex[:10]}",
                            org_id=actor.active_org_id,
                            case_id=case.case_id,
                            event_type="CSV_IMPORTED",
                            actor_uid=actor.uid,
                            payload={"job_id": job.job_id},
                        )
                    )
                    job.produced_case_ids.append(case.case_id)
                    job.success_count += 1
            elif target == "teams":
                for row in rows:
                    team_id = row.get("team_id") or f"TEAM-{uuid.uuid4().hex[:6].upper()}"
                    capability_tags = [item.strip().upper() for item in (row.get("capability_tags") or "").split(",") if item.strip()]
                    team = Team(
                        team_id=team_id,
                        org_id=actor.active_org_id,
                        display_name=row.get("display_name") or team_id,
                        capability_tags=capability_tags,
                        member_ids=[item.strip() for item in (row.get("member_ids") or "").split(",") if item.strip()],
                        service_radius_km=float(row.get("service_radius_km") or 30),
                        base_label=row.get("base_label") or row.get("location") or "Imported base",
                        current_label=row.get("current_label") or row.get("base_label") or row.get("location"),
                    )
                    team.base_geo = _geo_from_row(row, "base") or _geo_from_row(row, "")
                    team.current_geo = _geo_from_row(row, "current") or team.base_geo
                    if team.base_geo is None and team.base_label:
                        geo = await geocoder.geocode(team.base_label)
                        if geo is not None:
                            team.base_geo = GeoPoint(lat=geo.lat, lng=geo.lng)
                    if team.current_geo is None and team.current_label:
                        geo = await geocoder.geocode(team.current_label)
                        if geo is not None:
                            team.current_geo = GeoPoint(lat=geo.lat, lng=geo.lng)
                    repository.save_team(team)
                    tokens = token_service.from_csv_row(
                        source_ref=job.job_id,
                        row=row,
                        token_type=InfoTokenType.TEAM_CAPABILITY,
                        linked_entity_type="TEAM",
                        linked_entity_id=team.team_id,
                    )
                    for token in tokens:
                        token.org_id = actor.active_org_id
                    repository.save_info_tokens(None, tokens)
                    job.produced_token_ids.extend([item.token_id for item in tokens])
                    job.success_count += 1
            elif target == "resources":
                for row in rows:
                    resource = ResourceInventory(
                        resource_id=row.get("resource_id") or f"RES-{uuid.uuid4().hex[:6].upper()}",
                        org_id=actor.active_org_id,
                        owning_team_id=row.get("owning_team_id") or None,
                        resource_type=row.get("resource_type") or "GENERIC_RESOURCE",
                        quantity_available=float(row.get("quantity_available") or 0),
                        location_label=row.get("location_label") or row.get("location") or "Imported resource",
                        current_label=row.get("current_label") or row.get("location_label") or row.get("location"),
                        constraints=[item.strip() for item in (row.get("constraints") or "").split(",") if item.strip()],
                    )
                    resource.location = _geo_from_row(row, "location") or _geo_from_row(row, "")
                    resource.current_geo = _geo_from_row(row, "current") or resource.location
                    if resource.location is None and resource.location_label:
                        geo = await geocoder.geocode(resource.location_label)
                        if geo is not None:
                            resource.location = GeoPoint(lat=geo.lat, lng=geo.lng)
                    if resource.current_geo is None and resource.current_label:
                        geo = await geocoder.geocode(resource.current_label)
                        if geo is not None:
                            resource.current_geo = GeoPoint(lat=geo.lat, lng=geo.lng)
                    repository.save_resource(resource)
                    tokens = token_service.from_csv_row(
                        source_ref=job.job_id,
                        row=row,
                        token_type=InfoTokenType.RESOURCE_CAPABILITY,
                        linked_entity_type="RESOURCE",
                        linked_entity_id=resource.resource_id,
                    )
                    for token in tokens:
                        token.org_id = actor.active_org_id
                    repository.save_info_tokens(None, tokens)
                    job.produced_token_ids.extend([item.token_id for item in tokens])
                    job.success_count += 1
            else:
                raise ValueError(f"Unsupported CSV target '{target}'.")
        else:
            if evidence_id:
                evidence = repository.get_evidence(evidence_id)
                evidence.status = EvidenceStatus.UPLOADED
                evidence.incident_id = linked_case_id
                if storage_path:
                    evidence.storage_path = storage_path
                repository.save_evidence(evidence)
            else:
                registration = repository.register_upload(
                    UploadRegistrationRequest(
                        filename=resolved_filename,
                        content_type=resolved_content_type,
                        size_bytes=len(content),
                        linked_entity_type="INCIDENT",
                        linked_entity_id=linked_case_id,
                    ),
                    actor,
                )
                evidence = registration.evidence_item
                evidence.status = EvidenceStatus.UPLOADED
                evidence.incident_id = linked_case_id
                repository.save_evidence(evidence)
            extraction = extractor.extract_document(
                evidence.filename,
                evidence.content_type,
                content,
            )
            target_case_id = linked_case_id
            if target_case_id is None:
                new_case = repository.create_case(extraction.notes_for_dispatch or evidence.filename, "FILE_IMPORT", actor)
                target_case_id = new_case.case_id
                job.produced_case_ids.append(target_case_id)
            repository.save_extraction(target_case_id, extraction, status="EXTRACTED")
            geo = await geocoder.geocode(extraction.location_text)
            if geo is not None:
                repository.update_case_location(
                    target_case_id,
                    extraction.location_text,
                    geo.lat,
                    geo.lng,
                    LocationConfidence.APPROXIMATE if extraction.data_quality.missing_location else LocationConfidence.EXACT,
                )
            rationale = scorer.score(extraction)
            repository.save_scoring(target_case_id, rationale.final_score, rationale, rationale.final_urgency)
            tokens = token_service.from_incident(repository.get_case(target_case_id), extraction)
            repository.save_info_tokens(target_case_id, tokens)
            evidence.incident_id = target_case_id
            evidence.status = EvidenceStatus.PROCESSED
            evidence.extracted_text = extraction.notes_for_dispatch
            repository.save_evidence(evidence)
            job.evidence_id = evidence.evidence_id
            job.produced_token_ids.extend([item.token_id for item in tokens])
            job.success_count = 1

        job.status = IngestionStatus.COMPLETED
        job.completed_at = datetime.now(tz=UTC)
    except Exception as exc:
        job.status = IngestionStatus.FAILED
        job.error_message = str(exc)
        job.completed_at = datetime.now(tz=UTC)
        raise
    finally:
        repository.save_ingestion_job(job)
    return job


def _geo_from_row(row: dict[str, str], prefix: str) -> GeoPoint | None:
    candidates = []
    if prefix:
        candidates.extend(
            [
                (f"{prefix}_lat", f"{prefix}_lng"),
                (f"{prefix}_latitude", f"{prefix}_longitude"),
            ]
        )
    else:
        candidates.extend([("lat", "lng"), ("latitude", "longitude")])
    for lat_key, lng_key in candidates:
        lat_raw = row.get(lat_key)
        lng_raw = row.get(lng_key)
        if not lat_raw or not lng_raw:
            continue
        try:
            return GeoPoint(lat=float(lat_raw), lng=float(lng_raw))
        except ValueError:
            return None
    return None
