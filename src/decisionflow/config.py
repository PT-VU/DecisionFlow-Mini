from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .models import ExecutionMode


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


@dataclass(frozen=True)
class Settings:
    """Environment-only configuration with safe mock defaults.

    Secrets are deliberately represented as strings only at the process edge;
    this object never serializes them or exposes them through health endpoints.
    """

    mode: str = "mock"
    execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    data_root: Path = Path("data/public")
    run_store: str = "memory"
    audit_store: str = "memory"
    audit_db: Path = Path("runtime/decisionflow.db")
    provider: str = "mock"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str | None = None
    azure_openai_entra: bool = False
    azure_storage_account_url: str | None = None
    azure_storage_queue_url: str | None = None
    azure_blob_container: str = "decisionflow-artifacts"
    azure_queue_name: str = "decisionflow-jobs"
    queue_backend: str = "local"
    key_vault_url: str | None = None
    api_key: str | None = None
    bridge_token: str | None = None
    codex_workspace_root: Path | None = None
    codex_command: str = "codex"
    request_timeout_seconds: float = 30.0
    rate_limit_per_minute: int = 120

    @classmethod
    def from_env(cls) -> "Settings":
        raw_execution = _optional_env("DECISIONFLOW_EXECUTION_MODE") or ExecutionMode.DETERMINISTIC.value
        try:
            execution_mode = ExecutionMode(raw_execution)
        except ValueError as exc:
            raise ValueError(f"Unsupported DECISIONFLOW_EXECUTION_MODE: {raw_execution}") from exc
        return cls(
            mode=_optional_env("DECISIONFLOW_MODE") or "mock",
            execution_mode=execution_mode,
            data_root=Path(_optional_env("DECISIONFLOW_DATA_ROOT") or "data/public"),
            run_store=_optional_env("DECISIONFLOW_RUN_STORE") or "memory",
            audit_store=_optional_env("DECISIONFLOW_AUDIT_STORE") or "memory",
            audit_db=Path(_optional_env("DECISIONFLOW_AUDIT_DB") or "runtime/decisionflow.db"),
            provider=_optional_env("DECISIONFLOW_PROVIDER") or "mock",
            llm_base_url=_optional_env("LLM_BASE_URL"),
            llm_api_key=_optional_env("LLM_API_KEY"),
            llm_model=_optional_env("LLM_MODEL"),
            azure_openai_endpoint=_optional_env("AZURE_OPENAI_ENDPOINT"),
            azure_openai_deployment=_optional_env("AZURE_OPENAI_DEPLOYMENT"),
            azure_openai_api_version=_optional_env("AZURE_OPENAI_API_VERSION"),
            azure_openai_entra=(_optional_env("AZURE_OPENAI_USE_ENTRA") or "false").lower() in {"1", "true", "yes"},
            azure_storage_account_url=_optional_env("AZURE_STORAGE_ACCOUNT_URL"),
            azure_storage_queue_url=_optional_env("AZURE_STORAGE_QUEUE_URL"),
            azure_blob_container=_optional_env("AZURE_BLOB_CONTAINER") or "decisionflow-artifacts",
            azure_queue_name=_optional_env("AZURE_QUEUE_NAME") or "decisionflow-jobs",
            queue_backend=_optional_env("DECISIONFLOW_QUEUE_BACKEND") or "local",
            key_vault_url=_optional_env("KEY_VAULT_URL"),
            api_key=_optional_env("DECISIONFLOW_API_KEY"),
            bridge_token=_optional_env("DECISIONFLOW_BRIDGE_TOKEN"),
            codex_workspace_root=Path(_optional_env("CODEX_WORKSPACE_ROOT"))
            if _optional_env("CODEX_WORKSPACE_ROOT")
            else None,
            codex_command=_optional_env("CODEX_COMMAND") or "codex",
            request_timeout_seconds=float(_optional_env("DECISIONFLOW_REQUEST_TIMEOUT_SECONDS") or "30"),
            rate_limit_per_minute=int(_optional_env("DECISIONFLOW_RATE_LIMIT_PER_MINUTE") or "120"),
        )

    def validate_readiness(self) -> list[str]:
        """Return configuration errors without leaking secret values."""
        errors: list[str] = []
        if self.run_store == "azure_table" or self.audit_store == "azure_table":
            if not self.azure_storage_account_url:
                errors.append("AZURE_STORAGE_ACCOUNT_URL is required for Azure Table storage")
        if self.provider != "mock" and not self.llm_api_key and self.provider not in {"codex_bridge", "azure_openai"}:
            errors.append("LLM_API_KEY is required for the selected provider")
        if self.provider in {"deepseek", "openai_compatible"} and not self.llm_base_url:
            errors.append("LLM_BASE_URL is required for the selected provider")
        if self.provider == "azure_openai" and not (self.azure_openai_endpoint or self.llm_base_url):
            errors.append("AZURE_OPENAI_ENDPOINT or LLM_BASE_URL is required for azure_openai")
        if self.provider == "azure_openai" and not (self.azure_openai_deployment or self.llm_model):
            errors.append("AZURE_OPENAI_DEPLOYMENT or LLM_MODEL is required for azure_openai")
        if self.execution_mode == ExecutionMode.LOCAL_CODEX_DEV and not self.codex_workspace_root:
            errors.append("CODEX_WORKSPACE_ROOT is required for local_codex_dev")
        if self.rate_limit_per_minute < 1:
            errors.append("DECISIONFLOW_RATE_LIMIT_PER_MINUTE must be positive")
        if (self.run_store == "azure_table") != (self.audit_store == "azure_table"):
            errors.append("Azure run store and audit store must be enabled together")
        return errors

    def public_dict(self) -> dict[str, str | int | None]:
        """Safe configuration summary suitable for readiness diagnostics."""
        return {
            "mode": self.mode,
            "execution_mode": self.execution_mode.value,
            "provider": self.provider,
            "run_store": self.run_store,
            "audit_store": self.audit_store,
            "queue_backend": self.queue_backend,
            "data_root": str(self.data_root),
            "rate_limit_per_minute": self.rate_limit_per_minute,
        }


def dataset_hash(root: Path) -> str:
    """Stable hash of the public, runtime-readable fixture."""
    digest = hashlib.sha256()
    if not root.exists():
        return "sha256:" + digest.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()
