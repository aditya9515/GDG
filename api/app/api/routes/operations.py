from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.core.dependencies import (
    get_agent_graph_service,
    get_extraction_service,
    get_geocoding_service,
    get_repository,
    get_scoring_service,
    get_storage_bridge_service,
    get_token_service,
    get_vector_service,
)
from app.core.config import get_settings
from app.core.security import get_current_org_user, get_current_user
from app.models.domain import (
    AuthSessionResponse,
    CaseEvent,
    CreateResourceRequest,
    CreateTeamRequest,
    CreateVolunteerRequest,
    DeleteResponse,
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
    Volunteer,
    ResourceInventory,
    VectorRecord,
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
def list_teams(q: str | None = Query(default=None), actor: UserContext = Depends(get_current_org_user)):
    items = [item for item in get_repository().list_teams() if item.org_id == actor.active_org_id]
    return TeamsResponse(items=_sort_newest(_filter_items(items, q, ["team_id", "display_name", "base_label", "current_label", "capability_tags"])))


@router.post("/teams", response_model=Team)
def create_team(payload: CreateTeamRequest, actor: UserContext = Depends(get_current_org_user)):
    team = Team(
        team_id=f"TEAM-{uuid.uuid4().hex[:8].upper()}",
        org_id=actor.active_org_id,
        display_name=payload.display_name.strip(),
        capability_tags=_normalize_tags(payload.capability_tags),
        member_ids=payload.member_ids,
        service_radius_km=payload.service_radius_km,
        base_label=payload.base_label,
        base_geo=payload.base_geo,
        current_label=payload.current_label or payload.base_label,
        current_geo=payload.current_geo or payload.base_geo,
        availability_status=payload.availability_status,
        reliability_score=payload.reliability_score,
    )
    return get_repository().save_team(team)


@router.delete("/teams/{team_id}", response_model=DeleteResponse)
def delete_team(team_id: str, actor: UserContext = Depends(get_current_org_user)):
    try:
        get_repository().delete_team(team_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Team not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return DeleteResponse(deleted_id=team_id, deleted_type="team", request_id=f"req-{uuid.uuid4().hex[:12]}")


@router.get("/volunteers", response_model=VolunteersResponse)
def list_volunteers(q: str | None = Query(default=None), actor: UserContext = Depends(get_current_org_user)):
    items = [item for item in get_repository().list_volunteers() if item.org_id == actor.active_org_id]
    return VolunteersResponse(items=_sort_newest(_filter_items(items, q, ["volunteer_id", "display_name", "team_id", "home_base_label", "skills", "role_tags"])))


@router.post("/volunteers", response_model=Volunteer)
def create_volunteer(payload: CreateVolunteerRequest, actor: UserContext = Depends(get_current_org_user)):
    volunteer = Volunteer(
        volunteer_id=f"VOL-{uuid.uuid4().hex[:8].upper()}",
        org_id=actor.active_org_id,
        team_id=payload.team_id,
        display_name=payload.display_name.strip(),
        role_tags=_normalize_tags(payload.role_tags),
        skills=_normalize_tags(payload.skills),
        home_base_label=payload.home_base_label,
        home_base=payload.home_base,
        current_geo=payload.current_geo or payload.home_base,
        availability_status=payload.availability_status,
        max_concurrent_assignments=payload.max_concurrent_assignments,
        reliability_score=payload.reliability_score,
    )
    saved = get_repository().save_volunteer(volunteer)
    if saved.team_id:
        teams = [item for item in get_repository().list_teams() if item.org_id == actor.active_org_id and item.team_id == saved.team_id]
        if teams and saved.volunteer_id not in teams[0].member_ids:
            teams[0].member_ids.append(saved.volunteer_id)
            get_repository().save_team(teams[0])
    return saved


@router.delete("/volunteers/{volunteer_id}", response_model=DeleteResponse)
def delete_volunteer(volunteer_id: str, actor: UserContext = Depends(get_current_org_user)):
    try:
        get_repository().delete_volunteer(volunteer_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Volunteer not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return DeleteResponse(deleted_id=volunteer_id, deleted_type="volunteer", request_id=f"req-{uuid.uuid4().hex[:12]}")


@router.get("/resources", response_model=ResourcesResponse)
def list_resources(q: str | None = Query(default=None), actor: UserContext = Depends(get_current_org_user)):
    items = [item for item in get_repository().list_resources() if item.org_id == actor.active_org_id]
    return ResourcesResponse(items=_sort_newest(_filter_items(items, q, ["resource_id", "resource_type", "location_label", "current_label", "owning_team_id", "constraints"])))


@router.post("/resources", response_model=ResourceInventory)
def create_resource(payload: CreateResourceRequest, actor: UserContext = Depends(get_current_org_user)):
    resource = ResourceInventory(
        resource_id=f"RES-{uuid.uuid4().hex[:8].upper()}",
        org_id=actor.active_org_id,
        owning_team_id=payload.owning_team_id,
        resource_type=payload.resource_type.strip().upper().replace(" ", "_"),
        quantity_available=payload.quantity_available,
        location_label=payload.location_label,
        location=payload.location,
        current_label=payload.current_label or payload.location_label,
        current_geo=payload.current_geo or payload.location,
        constraints=_normalize_tags(payload.constraints),
    )
    return get_repository().save_resource(resource)


@router.delete("/resources/{resource_id}", response_model=DeleteResponse)
def delete_resource(resource_id: str, actor: UserContext = Depends(get_current_org_user)):
    try:
        get_repository().delete_resource(resource_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return DeleteResponse(deleted_id=resource_id, deleted_type="resource", request_id=f"req-{uuid.uuid4().hex[:12]}")


@router.get("/dispatches", response_model=DispatchListResponse)
def list_dispatches(q: str | None = Query(default=None), actor: UserContext = Depends(get_current_org_user)):
    items = [item for item in get_repository().list_assignments() if item.org_id == actor.active_org_id]
    return DispatchListResponse(items=_sort_newest(_filter_items(items, q, ["assignment_id", "case_id", "team_id", "volunteer_ids", "resource_ids"])))


@router.delete("/dispatches/{assignment_id}", response_model=DeleteResponse)
def delete_dispatch(assignment_id: str, actor: UserContext = Depends(get_current_org_user)):
    try:
        get_repository().delete_assignment(assignment_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dispatch not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return DeleteResponse(deleted_id=assignment_id, deleted_type="dispatch", request_id=f"req-{uuid.uuid4().hex[:12]}")


@router.post("/uploads/register", response_model=UploadRegistrationResponse)
def register_upload(
    payload: UploadRegistrationRequest,
    actor: UserContext = Depends(get_current_org_user),
):
    return get_repository().register_upload(payload, actor)


@router.get("/ingestion-jobs", response_model=IngestionJobsResponse)
def list_ingestion_jobs(q: str | None = Query(default=None), actor: UserContext = Depends(get_current_org_user)):
    items = [item for item in get_repository().list_ingestion_jobs() if item.org_id == actor.active_org_id]
    return IngestionJobsResponse(items=_sort_newest(_filter_items(items, q, ["job_id", "filename", "target", "kind", "status"])))


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJob)
def get_ingestion_job(job_id: str, actor: UserContext = Depends(get_current_org_user)):
    job = get_repository().get_ingestion_job(job_id)
    if job.org_id != actor.active_org_id:
        raise HTTPException(status_code=403, detail="Ingestion job belongs to another organization.")
    return job


@router.delete("/ingestion-jobs/{job_id}", response_model=DeleteResponse)
def delete_ingestion_job(job_id: str, actor: UserContext = Depends(get_current_org_user)):
    try:
        get_repository().delete_ingestion_job(job_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Ingestion job not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return DeleteResponse(deleted_id=job_id, deleted_type="ingestion_job", request_id=f"req-{uuid.uuid4().hex[:12]}")


@router.post("/ingestion-jobs", response_model=IngestionJob)
async def create_ingestion_job(
    kind: IngestionKind = Form(...),
    target: str = Form(...),
    linked_case_id: str | None = Form(default=None),
    evidence_id: str | None = Form(default=None),
    storage_path: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    content_type: str | None = Form(default=None),
    import_mode: str = Form(default="auto_commit"),
    file: UploadFile | None = File(default=None),
    actor: UserContext = Depends(get_current_org_user),
):
    repository = get_repository()
    extractor = get_extraction_service()
    geocoder = get_geocoding_service()
    scorer = get_scoring_service()
    storage_bridge = get_storage_bridge_service()
    token_service = get_token_service()
    vector_service = get_vector_service()

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

        if import_mode == "dry_run":
            if kind == IngestionKind.CSV:
                try:
                    job.row_count = len(list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")))))
                except Exception:
                    job.row_count = 0
            job.status = IngestionStatus.COMPLETED
            job.completed_at = datetime.now(tz=UTC)
            job.error_message = "Dry run completed without committing records."
            return job
        if import_mode == "preview":
            raise ValueError("Use /agent/graph1/run-file for preview imports.")
        if import_mode != "auto_commit":
            raise ValueError("import_mode must be auto_commit, preview, or dry_run.")

        if kind == IngestionKind.CSV:
            text = content.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            job.row_count = len(rows)
            graph_run = get_agent_graph_service().run_graph1_file(
                filename=resolved_filename,
                content_type=resolved_content_type,
                content=content,
                source_kind="CSV",
                target=target,
                operator_prompt=None,
                actor=actor,
            )
            confirmed = get_agent_graph_service().confirm_graph1(graph_run.run_id, actor)
            job.success_count = len(confirmed.committed_record_ids)
            job.warning_count = confirmed.meta.get("warning_count", 0) if isinstance(confirmed.meta.get("warning_count"), int) else 0
            job.produced_case_ids.extend([item for item in confirmed.committed_record_ids if item.startswith("CASE-")])
            committed_ids = set(confirmed.committed_record_ids)
            job.produced_token_ids.extend(
                [
                    token.token_id
                    for token in repository.list_info_tokens(None)
                    if token.org_id == actor.active_org_id and token.linked_entity_id in committed_ids
                ]
            )
            job.error_message = "Auto-commit completed through Graph 1 shared extraction and commit pipeline."
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
            batch_result = extractor.extract_document_file_batch_with_metadata(
                evidence.filename,
                evidence.content_type,
                content,
            )
            batch = batch_result.batch
            if not batch.incidents and not batch.teams and not batch.resources:
                extraction = extractor.extract_document(evidence.filename, evidence.content_type, content)
                batch.incidents.append(extraction)
            for extraction in batch.incidents:
                target_case_id = linked_case_id
                if target_case_id is None:
                    new_case = repository.create_case(extraction.notes_for_dispatch or evidence.filename, "FILE_IMPORT", actor)
                    target_case_id = new_case.case_id
                    job.produced_case_ids.append(target_case_id)
                case = repository.save_extraction(target_case_id, extraction, status="EXTRACTED")
                geo = await geocoder.geocode(extraction.location_text)
                if geo is not None:
                    case = repository.update_case_location(
                        target_case_id,
                        extraction.location_text,
                        geo.lat,
                        geo.lng,
                        LocationConfidence.APPROXIMATE if extraction.data_quality.missing_location else LocationConfidence.EXACT,
                    )
                rationale = scorer.score(extraction)
                case = repository.save_scoring(target_case_id, rationale.final_score, rationale, rationale.final_urgency)
                tokens = token_service.from_incident(case, extraction)
                repository.save_info_tokens(target_case_id, tokens)
                vector_text = vector_service.build_incident_embedding_text(case, extraction)
                repository.save_vector_records(
                    [
                        VectorRecord(
                            vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                            org_id=actor.active_org_id or "unassigned",
                            record_type="INCIDENT",
                            record_id=case.case_id,
                            token_id=tokens[0].token_id if tokens else None,
                            embedding=vector_service.embed(vector_text),
                            text=vector_text,
                            metadata={"category": extraction.category, "urgency": extraction.urgency},
                            source_refs=[evidence.evidence_id],
                            created_by=actor.uid,
                        )
                    ]
                )
                job.produced_token_ids.extend([item.token_id for item in tokens])
                job.success_count += 1
            for index, team_payload in enumerate(batch.teams, start=1):
                team = Team(
                    team_id=f"TEAM-{uuid.uuid4().hex[:8].upper()}",
                    org_id=actor.active_org_id,
                    display_name=team_payload.display_name or f"Imported team {index}",
                    capability_tags=[item.upper().replace(" ", "_") for item in team_payload.capability_tags] or ["GENERAL_RESPONSE"],
                    member_ids=team_payload.member_ids,
                    base_label=team_payload.base_label or "Location pending",
                    current_label=team_payload.current_label or team_payload.base_label,
                    reliability_score=team_payload.reliability_score or 0.75,
                    notes=team_payload.notes,
                )
                if team.base_label and team.base_label != "Location pending":
                    geo = await geocoder.geocode(team.base_label)
                    if geo:
                        team.base_geo = GeoPoint(lat=geo.lat, lng=geo.lng)
                        team.current_geo = team.current_geo or team.base_geo
                repository.save_team(team)
                vector_text = vector_service.build_team_embedding_text(team)
                repository.save_vector_records(
                    [
                        VectorRecord(
                            vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                            org_id=actor.active_org_id or "unassigned",
                            record_type="TEAM",
                            record_id=team.team_id,
                            embedding=vector_service.embed(vector_text),
                            text=vector_text,
                            metadata={"capabilities": team.capability_tags},
                            source_refs=[evidence.evidence_id],
                            created_by=actor.uid,
                        )
                    ]
                )
                job.success_count += 1
            for resource_payload in batch.resources:
                resource = ResourceInventory(
                    resource_id=f"RES-{uuid.uuid4().hex[:8].upper()}",
                    org_id=actor.active_org_id,
                    owning_team_id=resource_payload.owning_team_id,
                    resource_type=resource_payload.resource_type,
                    quantity_available=resource_payload.quantity_available or 0,
                    location_label=resource_payload.location_label or "Location pending",
                    current_label=resource_payload.current_label or resource_payload.location_label,
                    constraints=resource_payload.constraints,
                )
                if resource.location_label and resource.location_label != "Location pending":
                    geo = await geocoder.geocode(resource.location_label)
                    if geo:
                        resource.location = GeoPoint(lat=geo.lat, lng=geo.lng)
                        resource.current_geo = resource.current_geo or resource.location
                repository.save_resource(resource)
                vector_text = vector_service.build_resource_embedding_text(resource)
                repository.save_vector_records(
                    [
                        VectorRecord(
                            vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                            org_id=actor.active_org_id or "unassigned",
                            record_type="RESOURCE",
                            record_id=resource.resource_id,
                            embedding=vector_service.embed(vector_text),
                            text=vector_text,
                            metadata={"resource_type": resource.resource_type},
                            source_refs=[evidence.evidence_id],
                            created_by=actor.uid,
                        )
                    ]
                )
                job.success_count += 1
            evidence.incident_id = job.produced_case_ids[0] if job.produced_case_ids else linked_case_id
            evidence.status = EvidenceStatus.PROCESSED
            evidence.extracted_text = batch.document_summary
            repository.save_evidence(evidence)
            job.evidence_id = evidence.evidence_id

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
        candidates.extend(
            [
                ("lat", "lng"),
                ("latitude", "longitude"),
                ("location_lat", "location_lng"),
                ("location_latitude", "location_longitude"),
            ]
        )
    for lat_key, lng_key in candidates:
        lat_raw = row.get(lat_key)
        lng_raw = row.get(lng_key)
        if not lat_raw or not lng_raw:
            continue
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except ValueError:
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        return GeoPoint(lat=lat, lng=lng)
    return None


def _normalize_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        for token in str(value).replace(";", ",").replace("|", ",").split(","):
            normalized = token.strip().upper().replace(" ", "_")
            if normalized and normalized not in tags:
                tags.append(normalized)
    return tags


def _field_text(item: object, field: str) -> str:
    value = getattr(item, field, "")
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return "" if value is None else str(value)


def _filter_items[T](items: list[T], q: str | None, fields: list[str]) -> list[T]:
    query = (q or "").strip().lower()
    if not query:
        return items
    return [
        item
        for item in items
        if query in " ".join(_field_text(item, field) for field in fields).lower()
    ]


def _sort_newest[T](items: list[T]) -> list[T]:
    def key(item: T) -> tuple[str, str]:
        timestamp = getattr(item, "updated_at", None) or getattr(item, "created_at", None) or getattr(item, "confirmed_at", None)
        identifier = (
            getattr(item, "case_id", None)
            or getattr(item, "team_id", None)
            or getattr(item, "volunteer_id", None)
            or getattr(item, "resource_id", None)
            or getattr(item, "assignment_id", None)
            or getattr(item, "job_id", None)
            or ""
        )
        return (str(timestamp or ""), str(identifier))

    return sorted(items, key=key, reverse=True)
