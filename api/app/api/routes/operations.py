from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.dependencies import (
    get_extraction_service,
    get_geocoding_service,
    get_repository,
    get_scoring_service,
    get_token_service,
)
from app.core.security import get_current_user
from app.models.domain import (
    CaseEvent,
    DispatchListResponse,
    EvidenceStatus,
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


@router.get("/teams", response_model=TeamsResponse)
def list_teams():
    return TeamsResponse(items=get_repository().list_teams())


@router.get("/volunteers", response_model=VolunteersResponse)
def list_volunteers():
    return VolunteersResponse(items=get_repository().list_volunteers())


@router.get("/resources", response_model=ResourcesResponse)
def list_resources():
    return ResourcesResponse(items=get_repository().list_resources())


@router.get("/dispatches", response_model=DispatchListResponse)
def list_dispatches():
    return DispatchListResponse(items=get_repository().list_assignments())


@router.post("/uploads/register", response_model=UploadRegistrationResponse)
def register_upload(
    payload: UploadRegistrationRequest,
    actor: UserContext = Depends(get_current_user),
):
    return get_repository().register_upload(payload, actor)


@router.get("/ingestion-jobs", response_model=IngestionJobsResponse)
def list_ingestion_jobs():
    return IngestionJobsResponse(items=get_repository().list_ingestion_jobs())


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJob)
def get_ingestion_job(job_id: str):
    return get_repository().get_ingestion_job(job_id)


@router.post("/ingestion-jobs", response_model=IngestionJob)
async def create_ingestion_job(
    kind: IngestionKind = Form(...),
    target: str = Form(...),
    linked_case_id: str | None = Form(default=None),
    file: UploadFile = File(...),
    actor: UserContext = Depends(get_current_user),
):
    repository = get_repository()
    extractor = get_extraction_service()
    geocoder = get_geocoding_service()
    scorer = get_scoring_service()
    token_service = get_token_service()

    job = IngestionJob(
        job_id=f"job-{uuid.uuid4().hex[:10]}",
        kind=kind,
        target=target,
        filename=file.filename or "upload.bin",
        status=IngestionStatus.PROCESSING,
        created_by=actor.uid,
    )
    repository.create_ingestion_job(job)

    try:
        content = await file.read()
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
                        display_name=row.get("display_name") or team_id,
                        capability_tags=capability_tags,
                        member_ids=[item.strip() for item in (row.get("member_ids") or "").split(",") if item.strip()],
                        service_radius_km=float(row.get("service_radius_km") or 30),
                        base_label=row.get("base_label") or row.get("location") or "Imported base",
                        current_label=row.get("current_label") or row.get("base_label") or row.get("location"),
                    )
                    repository.save_team(team)
                    tokens = token_service.from_csv_row(
                        source_ref=job.job_id,
                        row=row,
                        token_type=InfoTokenType.TEAM_CAPABILITY,
                        linked_entity_type="TEAM",
                        linked_entity_id=team.team_id,
                    )
                    repository.save_info_tokens(None, tokens)
                    job.produced_token_ids.extend([item.token_id for item in tokens])
                    job.success_count += 1
            elif target == "resources":
                for row in rows:
                    resource = ResourceInventory(
                        resource_id=row.get("resource_id") or f"RES-{uuid.uuid4().hex[:6].upper()}",
                        owning_team_id=row.get("owning_team_id") or None,
                        resource_type=row.get("resource_type") or "GENERIC_RESOURCE",
                        quantity_available=float(row.get("quantity_available") or 0),
                        location_label=row.get("location_label") or row.get("location") or "Imported resource",
                        current_label=row.get("current_label") or row.get("location_label") or row.get("location"),
                        constraints=[item.strip() for item in (row.get("constraints") or "").split(",") if item.strip()],
                    )
                    repository.save_resource(resource)
                    tokens = token_service.from_csv_row(
                        source_ref=job.job_id,
                        row=row,
                        token_type=InfoTokenType.RESOURCE_CAPABILITY,
                        linked_entity_type="RESOURCE",
                        linked_entity_id=resource.resource_id,
                    )
                    repository.save_info_tokens(None, tokens)
                    job.produced_token_ids.extend([item.token_id for item in tokens])
                    job.success_count += 1
            else:
                raise ValueError(f"Unsupported CSV target '{target}'.")
        else:
            registration = repository.register_upload(
                UploadRegistrationRequest(
                    filename=file.filename or "upload.bin",
                    content_type=file.content_type or "application/octet-stream",
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
    except Exception as exc:
        job.status = IngestionStatus.FAILED
        job.error_message = str(exc)
        raise
    finally:
        repository.save_ingestion_job(job)
    return job
