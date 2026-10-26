from decisionflow.config import Settings


def test_azure_run_and_audit_stores_must_be_paired():
    errors = Settings(
        run_store="azure_table",
        audit_store="memory",
        azure_storage_account_url="https://example.table.core.windows.net",
    ).validate_readiness()
    assert any("must be enabled together" in error for error in errors)
