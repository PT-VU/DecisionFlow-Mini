from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .api_auth import RateLimiter, authenticated_request
from .config import Settings
from .jobs import JobWorker, LocalJobQueue
from .jobs.azure_storage_queue import AzureStorageQueue
from .llm import build_provider
from .models import JobEnvelope, ReviewRecord, RunAccepted, RunRequest, Ticket, WorkflowResult, WorkflowStatus
from .stores.azure_table import AzureTableAuditStore, AzureTableRunStore
from .workflow import DecisionFlowWorkflow


def default_data_root() -> Path:
    configured = os.getenv("DECISIONFLOW_DATA_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "data" / "public"


def create_app(
    workflow: DecisionFlowWorkflow | None = None,
    *,
    settings: Settings | None = None,
    queue=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    audit_path = settings.audit_db if settings.audit_store == "sqlite" else None
    provider = build_provider(settings)
    if workflow is None and settings.run_store == "azure_table":
        if not settings.azure_storage_account_url:
            raise ValueError("AZURE_STORAGE_ACCOUNT_URL is required for azure_table run store")
        azure_run_store = AzureTableRunStore(settings.azure_storage_account_url)
        azure_audit_store = (
            AzureTableAuditStore(settings.azure_storage_account_url)
            if settings.audit_store == "azure_table"
            else None
        )
        flow = DecisionFlowWorkflow(
            settings.data_root,
            run_store=azure_run_store,
            audit_store=azure_audit_store,
            provider=provider,
            provider_name=settings.provider,
        )
    else:
        flow = workflow or DecisionFlowWorkflow(
            settings.data_root,
            audit_path=audit_path,
            provider=provider,
            provider_name=settings.provider,
        )
    if queue is not None:
        job_queue = queue
    elif settings.queue_backend == "azure":
        if not settings.azure_storage_account_url:
            raise ValueError("AZURE_STORAGE_ACCOUNT_URL is required for Azure queue")
        queue_url = settings.azure_storage_queue_url or settings.azure_storage_account_url.replace(".table.", ".queue.")
        job_queue = AzureStorageQueue(queue_url, settings.azure_queue_name)
    else:
        job_queue = LocalJobQueue()
    worker = JobWorker(job_queue, flow)
    app = FastAPI(title="DecisionFlow Mini", version="0.2.0")
    app.state.settings = settings
    app.state.workflow = flow
    app.state.queue = job_queue
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            return JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error", "message": "Request failed"}, "request_id": request_id},
                headers={"x-request-id": request_id},
            )
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode, "provider": settings.provider}

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> dict:
        errors = settings.validate_readiness()
        if not flow.data_root.exists():
            errors.append(f"data root does not exist: {flow.data_root}")
        for name, component in (("run_store", flow.run_store), ("audit_store", flow.audit), ("queue", job_queue)):
            check = getattr(component, "health_check", None)
            if check is not None:
                try:
                    check()
                except Exception as exc:
                    errors.append(f"{name} data-plane check failed: {type(exc).__name__}")
        if errors:
            return JSONResponse(status_code=503, content={"status": "not_ready", "errors": errors})
        return {"status": "ready", "config": settings.public_dict(), "dataset_hash": flow.dataset_hash}

    @app.post("/v1/workflows", response_model=WorkflowResult)
    def run_workflow(ticket: Ticket, _auth=Depends(authenticated_request)) -> WorkflowResult:
        return flow.run(ticket)

    @app.get("/v1/workflows/{run_id}", response_model=WorkflowResult)
    def get_workflow(run_id: str, _auth=Depends(authenticated_request)) -> WorkflowResult:
        try:
            return flow.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": str(exc)}) from exc

    @app.post("/v1/workflows/{run_id}/reviews", response_model=WorkflowResult)
    def review_workflow(run_id: str, review: ReviewRecord, _auth=Depends(authenticated_request)) -> WorkflowResult:
        try:
            return flow.review(run_id, review)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "invalid_review", "message": str(exc)}) from exc

    @app.post("/v1/runs", response_model=RunAccepted, status_code=202)
    def create_run(
        request: RunRequest,
        background_tasks: BackgroundTasks,
        idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
        _auth=Depends(authenticated_request),
    ) -> RunAccepted:
        idempotency_key = request.idempotency_key or idempotency_header
        existing = (
            flow.run_store.find_by_idempotency_key(idempotency_key)
            if idempotency_key
            else None
        )
        if existing:
            return RunAccepted(
                run_id=existing.run_id,
                job_id=existing.job_id or existing.run_id,
                status=existing.status,
                execution_mode=existing.execution_mode,
            )
        run_id = str(uuid4())
        job_id = str(uuid4())
        pending = WorkflowResult(
            run_id=run_id,
            status=WorkflowStatus.RECEIVED,
            ticket=request.ticket,
            execution_mode=request.execution_mode,
            dataset_ref=request.dataset_ref,
            idempotency_key=idempotency_key,
            job_id=job_id,
        )
        try:
            flow.run_store.create(pending)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": str(exc)}) from exc
        flow.audit.save_snapshot(pending)
        job = JobEnvelope(
            job_id=job_id,
            run_id=run_id,
            execution_mode=request.execution_mode,
            payload_ref=run_id,
        )
        job_queue.enqueue(job)
        if isinstance(job_queue, LocalJobQueue):
            background_tasks.add_task(worker.process_one)
        return RunAccepted(run_id=run_id, job_id=job_id, status=WorkflowStatus.RECEIVED, execution_mode=request.execution_mode)

    @app.get("/v1/runs/{run_id}", response_model=WorkflowResult)
    def get_run(run_id: str, _auth=Depends(authenticated_request)) -> WorkflowResult:
        try:
            return flow.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": str(exc)}) from exc

    @app.get("/v1/runs/{run_id}/events")
    def get_run_events(run_id: str, _auth=Depends(authenticated_request)) -> list:
        try:
            flow.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": str(exc)}) from exc
        return [event.model_dump(mode="json") for event in flow.audit.events(run_id)]

    @app.post("/v1/runs/{run_id}/reviews", response_model=WorkflowResult)
    def review_run(run_id: str, review: ReviewRecord, _auth=Depends(authenticated_request)) -> WorkflowResult:
        try:
            return flow.review(run_id, review)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "invalid_review", "message": str(exc)}) from exc

    return app


app = create_app()

