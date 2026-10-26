from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from .adapter import DataAdapterAgent
from .data import PublicDataStore
from .models import (
    Action,
    Decision,
    DraftResponse,
    EvidenceItem,
    Family,
    Finding,
    FindingStatus,
    NormalizedTicket,
    ResponseClaim,
    RiskLevel,
    Route,
    Ticket,
)
from .provenance import make_evidence


FAMILY_KEYWORDS: dict[Family, tuple[str, ...]] = {
    Family.BILLING: ("invoice", "payment", "charge", "refund", "billing"),
    Family.ACCESS: ("access", "permission", "403", "role", "dashboard"),
    Family.KYC: ("kyc", "document", "verification", "identity", "upload"),
    Family.PRIVACY: ("delete", "export", "personal data", "privacy", "gdpr"),
    Family.AI_COMPLAINT: ("ai assistant", "bot", "wrong answer", "promised", "hallucinat"),
}

POLICY_TAGS: dict[Family, tuple[str, ...]] = {
    Family.BILLING: ("billing", "refund", "financial"),
    Family.ACCESS: ("access", "security", "finance_dashboard"),
    Family.KYC: ("kyc", "document", "compliance"),
    Family.PRIVACY: ("privacy", "personal_data"),
    Family.AI_COMPLAINT: ("ai_complaint", "ai", "governance"),
}


class IntakeAgent:
    def run(self, ticket: Ticket) -> NormalizedTicket:
        message = ticket.message.lower()
        category = ticket.family or max(
            FAMILY_KEYWORDS,
            key=lambda family: sum(keyword in message for keyword in FAMILY_KEYWORDS[family]),
        )
        sensitive = [signal for signal in ("personal data", "identity", "financial", "privacy", "bank") if signal in message]
        risk_hints = [signal for signal in ("urgent", "immediately", "delete", "admin", "wrong", "promised") if signal in message]
        missing: list[str] = []
        if not ticket.account_id:
            missing.append("account_id")
        if category == Family.BILLING and not any(token in message for token in ("inv-", "invoice", "payment", "charge")):
            missing.append("payment_or_invoice_reference")
        if not ticket.requester.authenticated:
            missing.append("authenticated_requester")
        urgency = "high" if any(word in message for word in ("urgent", "immediately", "critical")) else "medium"
        return NormalizedTicket(
            task_id=ticket.task_id,
            message=ticket.message,
            account_id=ticket.account_id,
            category=category,
            urgency=urgency,
            requester_role=ticket.requester.role,
            requester_authenticated=ticket.requester.authenticated,
            sensitive_signals=sensitive,
            risk_hints=risk_hints,
            missing_information=missing,
        )


class EvidenceRetrievalAgent:
    def __init__(self, store: PublicDataStore, adapter: DataAdapterAgent | None = None):
        self.store = store
        self.adapter = adapter or DataAdapterAgent(store)

    def run(
        self,
        ticket: Ticket,
        normalized: NormalizedTicket,
        *,
        allow_advisory: bool = True,
    ) -> list[EvidenceItem]:
        adapted = self.adapter.retrieve(ticket, normalized, allow_advisory=allow_advisory)
        if adapted:
            evidence = list(adapted)
            counter = len(evidence) + 1
            for section in self.store.policy_sections_by_id(self._policy_ids(ticket, normalized)):
                evidence.append(
                    make_evidence(
                        evidence_id=f"E-{counter:03d}",
                        source_id="policy_registry",
                        record_id=section["section_id"],
                        field_path="$",
                        value=section,
                        content=section["title"],
                        evidence_type="policy_section",
                        observed_at=ticket.created_at,
                    )
                )
                counter += 1
            return evidence
        evidence: list[EvidenceItem] = []
        counter = 1

        def add(**kwargs: object) -> None:
            nonlocal counter
            evidence.append(make_evidence(evidence_id=f"E-{counter:03d}", **kwargs))
            counter += 1

        add(
            source_id="ticket_system",
            record_id=ticket.task_id,
            field_path="$.message",
            value=ticket.message,
            content=ticket.message,
            evidence_type="source_record",
            observed_at=ticket.created_at,
        )
        for field, value in {
            "requester.role": ticket.requester.role,
            "requester.authenticated": ticket.requester.authenticated,
            **{f"public_context.{key}": value for key, value in ticket.public_context.items()},
        }.items():
            add(
                source_id="ticket_system",
                record_id=ticket.task_id,
                field_path=f"$.{field}",
                value=value,
                content=f"{field}: {value}",
                evidence_type="source_record",
                observed_at=ticket.created_at,
            )
        account = self.store.account(ticket.account_id)
        if account:
            for field in ("tier", "region", "risk_profile", "contract_status"):
                add(
                    source_id="account_registry",
                    record_id=account["account_id"],
                    field_path=f"$.{field}",
                    value=account.get(field),
                    content=f"Account {field}: {account.get(field)}",
                    evidence_type="source_record",
                    observed_at=ticket.created_at,
                )
        if normalized.category == Family.BILLING:
            payments = self.store.payments_for_account(ticket.account_id)
            add(
                source_id="payment_ledger",
                record_id=f"query:{ticket.account_id or 'missing'}",
                field_path="$.result_count",
                value=len(payments),
                content=f"Payment ledger query returned {len(payments)} record(s).",
                evidence_type="query_result",
                observed_at=ticket.created_at,
            )
            for payment in payments:
                add(
                    source_id="payment_ledger",
                    record_id=payment["payment_id"],
                    field_path="$",
                    value=payment,
                    content=f"Payment {payment['payment_id']} is {payment.get('state')} for {payment.get('amount')} {payment.get('currency')}.",
                    evidence_type="source_record",
                    observed_at=ticket.created_at,
                )
        for section in self.store.policy_sections_by_id(self._policy_ids(ticket, normalized)):
            add(
                source_id="policy_registry",
                record_id=section["section_id"],
                field_path="$",
                value=section,
                content=section["title"],
                evidence_type="policy_section",
                observed_at=ticket.created_at,
            )
        return evidence

    def _policy_ids(self, ticket: Ticket, normalized: NormalizedTicket) -> list[str]:
        facts = ticket.public_context
        message = ticket.message.lower()
        if ticket.dataset_version == "0.2.0":
            if normalized.category == Family.BILLING:
                ids = ["POL-BILL-001.S01"]
                if "duplicate" in message or "refund" in message or "dispute" in message:
                    ids.append("POL-REF-001.S01")
                if "dispute" in message:
                    ids.append("POL-REV-001.S03")
                return ids
            if normalized.category == Family.ACCESS:
                ids = ["POL-ACC-001.S01"]
                if "dashboard" in message or "administrator" in message:
                    ids.append("POL-DASH-001.S02")
                if ticket.requester.role == "external_consultant":
                    ids.append("POL-REV-001.S02")
                return ids
            if normalized.category == Family.KYC:
                ids = ["POL-KYC-001.S02", "POL-API-001.S01"]
                if "altered" in message or "approve" in message:
                    ids.append("POL-REV-001.S03")
                return ids
            if normalized.category == Family.PRIVACY:
                ids = ["POL-PRIV-001.S01"]
                if "active dispute" in message or "active" in message:
                    ids.append("POL-REV-001.S02")
                return ids
            ids = ["POL-AI-001.S01"]
            if "private" in message or "another user" in message:
                ids.extend(["POL-REV-001.S02", "POL-REV-001.S03"])
            elif "guaranteed" in message or "dispute" in message:
                ids.append("POL-REV-001.S03")
            return ids
        if normalized.category == Family.BILLING:
            issue = facts.get("issue")
            if issue in {"refund_status", "refund_pending", "refund_request"}:
                ids = ["POL-REF-001.S01"]
            elif issue == "ambiguous_payment_problem":
                ids = ["POL-BILL-001.S01", "POL-REF-001.S01"]
            elif issue == "duplicate_charge":
                ids = ["POL-BILL-001.S01", "POL-REF-001.S01"]
            else:
                ids = ["POL-BILL-001.S01"]
            if issue == "open_dispute":
                ids += ["POL-REF-001.S01", "POL-REV-001.S03"]
            if issue == "suspected_fraud":
                ids += ["POL-REV-001.S03"]
            if issue == "ai_refund_promise":
                ids += ["POL-AI-001.S01", "POL-REV-001.S03"]
            return ids
        if normalized.category == Family.ACCESS:
            ids = ["POL-ACC-001.S01"]
            scope = facts.get("requested_scope")
            resource = facts.get("resource")
            if resource == "finance_dashboard" and "renewal process" not in message or scope in {
                "assigned_account", "renewal_review", "all_customers", "administrator", "full"
            }:
                ids.append("POL-DASH-001.S02")
            if scope in {"all_customers", "administrator", "full"}:
                ids.append("POL-REV-001.S02")
            return ids
        if normalized.category == Family.KYC:
            ids = ["POL-KYC-001.S02"]
            if facts.get("upload_error") or facts.get("review_status") == "received" or "missing_fields" in facts:
                ids.append("POL-API-001.S01")
            if facts.get("document_status") in {"expired", "name_mismatch"} or facts.get("authenticity") == "uncertain":
                ids.append("POL-REV-001.S03")
            return ids
        if normalized.category == Family.PRIVACY:
            ids = ["POL-PRIV-001.S01"]
            if (
                not normalized.requester_authenticated
                or facts.get("legal_hold")
                or facts.get("sensitive_attachment")
                or facts.get("right") == "internal_data_request"
            ):
                ids.append("POL-REV-001.S02")
            return ids
        ids = ["POL-AI-001.S01"]
        incident = facts.get("incident")
        if incident == "privacy_disclosure":
            ids += ["POL-REV-001.S02", "POL-REV-001.S03"]
        elif incident in {"unsupported_refund_promise", "unauthorized_billing_change", "repeated_policy_violation"}:
            ids.append("POL-REV-001.S03")
        return ids


class FindingAgent:
    def run(self, ticket: Ticket, normalized: NormalizedTicket, evidence: list[EvidenceItem]) -> list[Finding]:
        if ticket.dataset_version == "0.2.0":
            return self._source_findings(ticket, normalized, evidence)
        findings: list[Finding] = []
        by_source: dict[str, list[EvidenceItem]] = {}
        for item in evidence:
            by_source.setdefault(item.locator.source_id, []).append(item)

        ticket_ev = by_source["ticket_system"][0]
        findings.append(
            Finding(
                finding_id="F-001",
                finding_type="fact",
                subject=ticket.task_id,
                claim=f"The requester reported a {normalized.category.value} issue.",
                value=normalized.category.value,
                status=FindingStatus.SUPPORTED,
                evidence_refs=[ticket_ev.locator.model_copy(deep=True)],
                derivation_method="direct_read",
                confidence="high" if ticket.family else "medium",
            )
        )
        account_evidence = by_source.get("account_registry", [])
        if account_evidence:
            tier = next((item for item in account_evidence if item.locator.field_path == "$.tier"), account_evidence[0])
            findings.append(
                Finding(
                    finding_id="F-002",
                    finding_type="fact",
                    subject=ticket.account_id or ticket.task_id,
                    claim=f"The account tier is {tier.value}.",
                    value=tier.value,
                    status=FindingStatus.SUPPORTED,
                    evidence_refs=[tier.locator.model_copy(deep=True)],
                    derivation_method="direct_read",
                    confidence="high",
                )
            )
        else:
            findings.append(
                Finding(
                    finding_id="F-002",
                    finding_type="unknown",
                    subject=ticket.task_id,
                    claim="The account tier could not be verified.",
                    status=FindingStatus.UNVERIFIED,
                    evidence_refs=[ticket_ev.locator.model_copy(deep=True)],
                    derivation_method="absence_query",
                    confidence="high",
                    requires_human_verification=True,
                )
            )
        if normalized.category == Family.BILLING:
            ledger = by_source.get("payment_ledger", [])
            query = next(item for item in ledger if item.locator.field_path == "$.result_count")
            records = [item for item in ledger if item.locator.field_path == "$"]
            duplicate_keys = Counter(
                (item.value.get("invoice_id"), item.value.get("amount"), item.value.get("currency"))
                for item in records
            )
            duplicate = any(count > 1 for count in duplicate_keys.values())
            findings.append(
                Finding(
                    finding_id="F-003",
                    finding_type="derived_fact" if duplicate else "unknown",
                    subject=ticket.account_id or ticket.task_id,
                    claim=("The ledger contains matching duplicate payment records." if duplicate else "A duplicate payment is not established by the available ledger records."),
                    value=duplicate,
                    status=FindingStatus.SUPPORTED if duplicate else FindingStatus.UNVERIFIED,
                    evidence_refs=[
                        query.locator.model_copy(deep=True),
                        *[item.locator.model_copy(deep=True) for item in records],
                    ],
                    derivation_method="normalized_join" if records else "absence_query",
                    rule_id="BILLING-DUPLICATE-KEY-V1",
                    confidence="high",
                    requires_human_verification=not duplicate,
                )
            )
        next_id = len(findings) + 1
        for item in by_source.get("ticket_system", []):
            prefix = "$.public_context."
            if not item.locator.field_path.startswith(prefix):
                continue
            field = item.locator.field_path.removeprefix(prefix)
            if field in {"evidence_refs", "case_reference"}:
                continue
            findings.append(
                Finding(
                    finding_id=f"F-{next_id:03d}",
                    finding_type="fact",
                    subject=f"public_context.{field}",
                    claim=f"The source record reports {field} as {item.value!r}.",
                    value=item.value,
                    status=FindingStatus.SUPPORTED,
                    evidence_refs=[item.locator.model_copy(deep=True)],
                    derivation_method="direct_read",
                    confidence="high",
                )
            )
            next_id += 1
        return findings

    def _source_findings(
        self, ticket: Ticket, normalized: NormalizedTicket, evidence: list[EvidenceItem]
    ) -> list[Finding]:
        """Derive facts from source values and relationships, never from a task id.

        ``task_id`` remains a trace identifier only.  The adapter can therefore
        replay the same source bundle under a new ticket id, and mutations to a
        payment, identity response, or policy record change the resulting fact
        rather than silently selecting a different hard-coded branch.
        """
        by_source: dict[str, list[EvidenceItem]] = defaultdict(list)
        by_record: dict[tuple[str, str], list[EvidenceItem]] = defaultdict(list)
        for item in evidence:
            by_source[item.locator.source_id].append(item)
            by_record[(item.locator.source_id, item.locator.record_id)].append(item)

        findings: list[Finding] = []
        next_id = 1

        def fields(source: str, field_path: str | None = None) -> list[EvidenceItem]:
            return [
                item
                for item in by_source.get(source, [])
                if field_path is None or item.locator.field_path == field_path
            ]

        def record_fields(source: str, predicate) -> list[EvidenceItem]:
            refs: list[EvidenceItem] = []
            for items in by_record.values():
                if not items or items[0].locator.source_id != source:
                    continue
                values = {item.locator.field_path: item.value for item in items}
                if predicate(values):
                    refs.extend(items)
            return refs

        def pick_record(source: str, predicate) -> tuple[list[EvidenceItem], dict[str, object]] | None:
            for items in by_record.values():
                if not items or items[0].locator.source_id != source:
                    continue
                values = {item.locator.field_path: item.value for item in items}
                if predicate(values):
                    return items, values
            return None

        def add(
            *,
            fact_key: str,
            claim: str,
            value: object,
            refs: list[EvidenceItem],
            finding_type: str = "fact",
            status: FindingStatus = FindingStatus.SUPPORTED,
            subject: str | None = None,
            conflict_refs: list[str] | None = None,
        ) -> None:
            nonlocal next_id
            if any(finding.fact_key == fact_key for finding in findings):
                return
            unique_refs = list(dict.fromkeys(item.locator.key for item in refs))
            refs = [next(item for item in refs if item.locator.key == key) for key in unique_refs]
            if not refs:
                return
            findings.append(
                Finding(
                    finding_id=f"F-{next_id:03d}",
                    finding_type=finding_type,
                    subject=subject or f"ticket:{ticket.task_id}",
                    claim=claim,
                    value=value,
                    status=status,
                    evidence_refs=[item.locator.model_copy(deep=True) for item in refs],
                    derivation_method="normalized_join" if len(refs) > 1 else "direct_read",
                    confidence="high" if status == FindingStatus.SUPPORTED else "medium",
                    requires_human_verification=status != FindingStatus.SUPPORTED,
                    fact_key=fact_key,
                    conflict_refs=conflict_refs or [],
                )
            )
            next_id += 1

        # Every migrated case must retain a source-backed record of the request.
        request_refs = [item for item in fields("src_ticket_system") if item.locator.field_path == "data.message"]
        add(
            fact_key="request_received",
            claim="The support request was received in the ticket system.",
            value=True,
            refs=request_refs,
        )

        if normalized.category == Family.BILLING:
            invoice = pick_record("src_invoice_order", lambda values: "data.payment_ids" in values)
            payment_records: list[tuple[list[EvidenceItem], dict[str, object]]] = []
            for items in by_record.values():
                if not items or items[0].locator.source_id != "src_payment_ledger":
                    continue
                values = {item.locator.field_path: item.value for item in items}
                if "data.state" in values:
                    payment_records.append((items, values))
            if invoice:
                invoice_items, invoice_values = invoice
                payment_ids = invoice_values.get("data.payment_ids")
                if isinstance(payment_ids, list):
                    matched = [
                        (items, values)
                        for items, values in payment_records
                        if items[0].locator.record_id in payment_ids
                        or values.get("data.invoice_id") == invoice_items[0].locator.record_id
                    ]
                    captured = [(items, values) for items, values in matched if values.get("data.state") == "captured"]
                    if len(captured) >= 2:
                        refs = [
                            *[item for item in invoice_items if item.locator.field_path == "data.payment_ids"],
                            *[item for items, _ in captured for item in items if item.locator.field_path == "data.state"],
                        ]
                        add(
                            fact_key="same_invoice_has_two_captures",
                            claim="The same invoice has two captured payments.",
                            value=True,
                            refs=refs,
                            subject=f"invoice:{invoice_items[0].locator.record_id}",
                        )

            dispute_status = [item for item in fields("src_acquirer_feed", "status")]
            partner_status = [item for item in fields("src_acquirer_feed", "data.status")]
            open_dispute = [item for item in partner_status if item.value == "open"]
            if open_dispute:
                add(
                    fact_key="external_dispute_is_open",
                    claim="The external payment partner reports an open dispute.",
                    value=True,
                    refs=open_dispute,
                    subject=f"payment:{open_dispute[0].locator.record_id}",
                )
                refund_not_started = [item for item in fields("src_payment_ledger", "data.status") if item.value == "not_started"]
                add(
                    fact_key="normal_refund_path_is_blocked",
                    claim="The normal refund path is not started while the dispute is open.",
                    value=True,
                    refs=[*open_dispute, *refund_not_started],
                    subject=f"payment:{open_dispute[0].locator.record_id}",
                )
            else:
                completed_absence = [item for item in dispute_status if item.value == "not_found"]
                add(
                    fact_key="no_partner_dispute_record_returned",
                    claim="No dispute record was returned by the completed acquirer query.",
                    value=True,
                    refs=completed_absence,
                    finding_type="absence",
                )

        elif normalized.category == Family.ACCESS:
            iam = pick_record("src_iam_directory", lambda values: "data.roles" in values)
            hr = pick_record("src_hr_role_directory", lambda values: "data.role" in values)
            resources = [
                (items, {item.locator.field_path: item.value for item in items})
                for items in by_record.values()
                if items and items[0].locator.source_id == "src_resource_registry"
            ]
            if iam and hr:
                iam_items, iam_values = iam
                hr_items, hr_values = hr
                iam_roles = iam_values.get("data.roles") or []
                hr_role = hr_values.get("data.role")
                if hr_role in iam_roles and iam_values.get("data.access_state") == "active":
                    add(
                        fact_key="current_role_matches_iam",
                        claim="The HR role matches the active IAM role.",
                        value=True,
                        refs=[
                            *[item for item in iam_items if item.locator.field_path == "data.roles"],
                            *[item for item in hr_items if item.locator.field_path == "data.role"],
                        ],
                    )
                for resource_items, resource_values in resources:
                    allowed_roles = resource_values.get("data.allowed_roles") or []
                    scope = iam_values.get("data.scope") or []
                    required_scope = resource_values.get("data.scope_required")
                    if required_scope in scope and any(role in allowed_roles for role in iam_roles):
                        add(
                            fact_key="scope_is_limited_to_assigned_account",
                            claim="The IAM scope is limited to the assigned account and the resource allows that role.",
                            value=True,
                            refs=[
                                *[item for item in iam_items if item.locator.field_path == "data.scope"],
                                *[item for item in resource_items if item.locator.field_path == "data.allowed_roles"],
                            ],
                        )
            if iam:
                iam_items, iam_values = iam
                iam_roles = iam_values.get("data.roles") or []
                for resource_items, resource_values in resources:
                    allowed_roles = resource_values.get("data.allowed_roles") or []
                    if iam_values.get("data.access_state") == "none" and "account_admin" not in iam_roles and "account_admin" in allowed_roles:
                        add(
                            fact_key="requester_has_no_admin_role",
                            claim="The requester has no administrator role in IAM.",
                            value=True,
                            refs=[
                                *[item for item in iam_items if item.locator.field_path in {"data.access_state", "data.roles"}],
                                *[item for item in resource_items if item.locator.field_path == "data.allowed_roles"],
                            ],
                        )
            approvals = fields("src_access_approvals", "status")
            denied = [item for item in approvals if item.value == "permission_denied"]
            not_found = [item for item in approvals if item.value == "not_found"]
            add(
                fact_key="customer_authorization_cannot_be_verified",
                claim="Customer authorization cannot be verified because the approval source denied access.",
                value=True,
                refs=denied,
                finding_type="absence",
                status=FindingStatus.UNVERIFIED,
            )
            add(
                fact_key="approval_record_status",
                claim="No separate access approval record was found.",
                value="not_found",
                refs=not_found,
                finding_type="absence",
                status=FindingStatus.UNVERIFIED,
            )

        elif normalized.category == Family.KYC:
            upload_error = record_fields("src_document_upload", lambda values: bool(values.get("data.error_code") or values.get("data.parser_status") == "rejected"))
            add(
                fact_key="upload_failed_with_structured_error",
                claim="The document upload failed with a structured parser error.",
                value=True,
                refs=[item for item in upload_error if item.locator.field_path in {"data.error_code", "data.http_status"}],
            )
            current_metadata = record_fields("src_document_metadata", lambda values: values.get("data.document_state") == "current")
            add(
                fact_key="document_metadata_is_current",
                claim="The document metadata says the submitted document is current.",
                value=True,
                refs=[item for item in current_metadata if item.locator.field_path in {"data.document_state", "data.expires_at"}],
            )
            uploads = {items[0].locator.record_id: {item.locator.field_path: item for item in items} for items in by_record.values() if items and items[0].locator.source_id == "src_document_upload"}
            metadata = {items[0].locator.record_id: {item.locator.field_path: item for item in items} for items in by_record.values() if items and items[0].locator.source_id == "src_document_metadata"}
            for record_id, upload_fields in uploads.items():
                upload_digest = upload_fields.get("data.uploaded_sha256")
                metadata_fields = metadata.get(record_id.replace("upload_", "doc_"), {})
                stored_digest = metadata_fields.get("data.stored_sha256")
                if upload_digest and stored_digest and upload_digest.value != stored_digest.value:
                    refs = [upload_digest, stored_digest]
                    add(
                        fact_key="document_digest_conflict",
                        claim="The uploaded and stored document digests do not match.",
                        value=True,
                        refs=refs,
                        finding_type="conflict",
                        conflict_refs=[item.locator.key for item in refs],
                    )
            unavailable = [item for item in fields("src_identity_provider", "status") if item.value in {"delayed", "partner_unavailable", "permission_denied"}]
            for item in unavailable:
                if item.value == "delayed":
                    add(
                        fact_key="identity_provider_status",
                        claim="The identity provider response is delayed.",
                        value="delayed",
                        refs=[item],
                        finding_type="absence",
                        status=FindingStatus.UNVERIFIED,
                    )
                else:
                    add(
                        fact_key="identity_authenticity_unverified",
                        claim="Identity authenticity is unverified because the identity provider is unavailable.",
                        value=True,
                        refs=[item],
                        finding_type="absence",
                        status=FindingStatus.UNVERIFIED,
                    )

        elif normalized.category == Family.PRIVACY:
            requests = record_fields("src_privacy_requests", lambda values: values.get("data.request_type") == "erasure")
            add(
                fact_key="erasure_request_received",
                claim="An erasure request for account data was received.",
                value=True,
                refs=[item for item in requests if item.locator.field_path in {"data.request_type", "data.status"}],
            )
            unverified_identity = [item for item in fields("src_customer_identity") if item.locator.field_path == "data.verification_state" and item.value == "unverified"]
            add(
                fact_key="requester_identity_is_unverified",
                claim="The customer identity is currently unverified.",
                value=True,
                refs=unverified_identity,
            )
            holds = record_fields("src_retention_legal_hold", lambda values: values.get("data.hold_state") == "active")
            if holds:
                request_scope = [item for item in requests if item.locator.field_path == "data.scope"]
                covered = [item for item in holds if item.locator.field_path == "data.covered_records"]
                hold_direct = [
                    item
                    for item in holds
                    if item.locator.field_path in {"data.hold_state", "data.covered_records", "data.reason"}
                ]
                add(
                    fact_key="erasure_request_covers_held_records",
                    claim="The erasure request covers records listed by the active legal hold.",
                    value=True,
                    refs=[*request_scope, *covered],
                    finding_type="conflict",
                    conflict_refs=[item.locator.key for item in hold_direct],
                )
                add(
                    fact_key="legal_hold_is_active",
                    claim="A legal hold is active for the account's dispute records.",
                    value=True,
                    refs=hold_direct,
                    finding_type="conflict",
                    conflict_refs=[item.locator.key for item in hold_direct],
                )
            denied_export = [item for item in fields("src_secure_export", "status") if item.value == "permission_denied"]
            add(
                fact_key="secure_export_status",
                claim="The secure export query is permission denied.",
                value="permission_denied",
                refs=denied_export,
                finding_type="absence",
                status=FindingStatus.UNVERIFIED,
            )

        elif normalized.category == Family.AI_COMPLAINT:
            transcripts = [
                (items, {item.locator.field_path: item.value for item in items})
                for items in by_record.values()
                if items and items[0].locator.source_id == "src_ai_transcript"
            ]
            for transcript_items, transcript in transcripts:
                messages = transcript.get("data.messages") or []
                text = " ".join(str(message.get("content", "")) for message in messages if isinstance(message, dict)).lower()
                if "guarantee" in text or "guaranteed" in text:
                    add(
                        fact_key="assistant_made_unsupported_refund_promise",
                        claim="The assistant transcript contains an unsupported refund guarantee.",
                        value=True,
                        refs=[item for item in transcript_items if item.locator.field_path in {"data.messages", "data.policy_version"}],
                    )
                if transcript.get("data.data_classification") == "financial":
                    add(
                        fact_key="ai_response_contains_financial_data",
                        claim="The AI response contains financial transaction data.",
                        value=True,
                        refs=[item for item in transcript_items if item.locator.field_path in {"data.data_classification", "data.messages"}],
                        finding_type="conflict",
                        conflict_refs=[item.locator.key for item in transcript_items],
                    )
                account_id = transcript.get("data.account_id")
                recipient = transcript.get("data.recipient_account_id")
                if account_id and recipient and account_id != recipient:
                    add(
                        fact_key="recipient_does_not_match_account",
                        claim="The transcript recipient account does not match the source account.",
                        value=True,
                        refs=[item for item in transcript_items if item.locator.field_path in {"data.account_id", "data.recipient_account_id"}],
                        finding_type="conflict",
                        conflict_refs=[item.locator.key for item in transcript_items],
                    )
            export_blocked = record_fields("src_secure_export", lambda values: values.get("data.authorization_state") in {"none", "missing"} and values.get("data.export_state") == "blocked")
            add(
                fact_key="export_is_blocked_without_authorization",
                claim="The secure export is blocked because authorization is absent.",
                value=True,
                refs=[item for item in export_blocked if item.locator.field_path in {"data.authorization_state", "data.export_state", "data.recipient_account_id"}],
                finding_type="conflict",
                conflict_refs=[item.locator.key for item in export_blocked],
            )
            open_dispute = [item for item in fields("src_acquirer_feed", "data.status") if item.value == "open"]
            captured_payment = [item for item in fields("src_payment_ledger", "data.state") if item.value == "captured"]
            add(
                fact_key="payment_has_open_external_dispute",
                claim="The payment has an open external dispute.",
                value=True,
                refs=[*open_dispute, *captured_payment],
                finding_type="conflict",
                conflict_refs=[item.locator.key for item in open_dispute],
            )
        return findings


class RiskRoutingAgent:
    _routes = {
        Family.BILLING: (Action.COLLECT_EVIDENCE, Route.BILLING_OPS),
        Family.ACCESS: (Action.ROUTE_ACCESS_REVIEW, Route.SECURITY_ACCESS),
        Family.KYC: (Action.ROUTE_KYC_REVIEW, Route.KYC_COMPLIANCE),
        Family.PRIVACY: (Action.ROUTE_PRIVACY_REVIEW, Route.PRIVACY_DPO),
        Family.AI_COMPLAINT: (Action.ROUTE_AI_INCIDENT_REVIEW, Route.AI_GOVERNANCE),
    }

    def run(self, normalized: NormalizedTicket, evidence: list[EvidenceItem], findings: list[Finding]) -> Decision:
        category = normalized.category
        facts = {
            f.subject.removeprefix("public_context."): f.value
            for f in findings
            if f.subject.startswith("public_context.")
        }
        facts.update({f.fact_key: f.value for f in findings if f.fact_key})
        action, route, risk, clarify = self._classify(category, normalized, facts)
        requires_review = risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        policy_refs = [item.locator.record_id for item in evidence if item.evidence_type == "policy_section"]
        return Decision(
            task_id=normalized.task_id,
            category=category,
            risk=risk,
            action=action,
            route=route,
            requires_clarification=clarify,
            requires_human_review=requires_review,
            finding_refs=[finding.finding_id for finding in findings],
            policy_refs=policy_refs,
            evidence_refs=[item.evidence_id for item in evidence],
            forbidden_actions=["execute_refund", "grant_access", "delete_data", "send_external_message"],
            response_constraints=[
                "Do not claim an external action was executed.",
                "Every factual response claim must reference a finding.",
                "Do not turn unverified findings into facts.",
            ],
            clarification_questions=(
                ["Please provide the missing identifier, scope, or source record required to investigate this request."]
                if clarify
                else []
            ),
        )

    def _classify(
        self, category: Family, normalized: NormalizedTicket, facts: dict[str, object]
    ) -> tuple[Action, Route, RiskLevel, bool]:
        message = normalized.message.lower()
        if category == Family.BILLING:
            if facts.get("external_dispute_is_open"):
                return Action.ROUTE_BILLING_REVIEW, Route.BILLING_OPS, RiskLevel.HIGH, False
            issue = facts.get("issue")
            if issue in {"refund_status", "refund_pending"}:
                return Action.ANSWER_WITH_EVIDENCE, Route.SUPPORT, RiskLevel.LOW, False
            if issue == "payment_descriptor":
                return Action.COLLECT_EVIDENCE, Route.BILLING_OPS, RiskLevel.LOW, False
            if issue in {"refund_request", "ambiguous_payment_problem"}:
                return Action.ASK_CLARIFICATION, Route.BILLING_OPS, RiskLevel.MEDIUM, True
            if issue == "open_dispute":
                return Action.ROUTE_BILLING_REVIEW, Route.BILLING_OPS, RiskLevel.HIGH, False
            if issue == "suspected_fraud":
                return Action.ROUTE_BILLING_REVIEW, Route.BILLING_OPS, RiskLevel.CRITICAL, False
            if issue == "ai_refund_promise":
                return Action.ROUTE_AI_INCIDENT_REVIEW, Route.AI_GOVERNANCE, RiskLevel.HIGH, False
            return Action.COLLECT_EVIDENCE, Route.BILLING_OPS, RiskLevel.MEDIUM, False

        if category == Family.ACCESS:
            if facts.get("requester_has_no_admin_role") and facts.get("customer_authorization_cannot_be_verified"):
                return Action.DENY_AUTOMATIC_ACTION, Route.HUMAN_REVIEW, RiskLevel.HIGH, False
            if facts.get("current_role_matches_iam") and facts.get("scope_is_limited_to_assigned_account"):
                return Action.COLLECT_EVIDENCE, Route.SECURITY_ACCESS, RiskLevel.MEDIUM, False
            scope, resource = facts.get("requested_scope"), facts.get("resource")
            if normalized.requester_role == "external_consultant" and scope == "administrator":
                return Action.DENY_AUTOMATIC_ACTION, Route.HUMAN_REVIEW, RiskLevel.HIGH, False
            if scope in {"all_customers", "full"} or normalized.requester_role == "former_finance_manager":
                return Action.ROUTE_ACCESS_REVIEW, Route.SECURITY_ACCESS, RiskLevel.HIGH, False
            if scope is None and not any(word in message for word in ("what roles", "renewal process")):
                return Action.ASK_CLARIFICATION, Route.SECURITY_ACCESS, RiskLevel.MEDIUM, True
            if facts.get("approver_reference") == "unverified":
                return Action.ASK_CLARIFICATION, Route.SECURITY_ACCESS, RiskLevel.MEDIUM, True
            if scope in {"assigned_account", "revoke"}:
                return Action.COLLECT_EVIDENCE, Route.SECURITY_ACCESS, RiskLevel.MEDIUM, False
            if resource in {"finance_dashboard", "customer_billing"}:
                return Action.ANSWER_WITH_EVIDENCE, Route.SECURITY_ACCESS, RiskLevel.LOW, False

        if category == Family.KYC:
            if facts.get("document_digest_conflict") or facts.get("identity_authenticity_unverified"):
                return Action.ROUTE_KYC_REVIEW, Route.KYC_COMPLIANCE, RiskLevel.HIGH, False
            if facts.get("upload_failed_with_structured_error") and facts.get("document_metadata_is_current"):
                return Action.COLLECT_EVIDENCE, Route.KYC_COMPLIANCE, RiskLevel.MEDIUM, False
            status = facts.get("document_status")
            if status in {"expired", "name_mismatch"} or facts.get("authenticity") == "uncertain":
                return Action.ROUTE_KYC_REVIEW, Route.KYC_COMPLIANCE, RiskLevel.HIGH, False
            if facts.get("document_type") in {None, "unknown"} or "missing_fields" in facts and facts.get("missing_fields") is None:
                return Action.ASK_CLARIFICATION, Route.KYC_COMPLIANCE, RiskLevel.MEDIUM, True
            if facts.get("upload_error"):
                return Action.COLLECT_EVIDENCE, Route.KYC_COMPLIANCE, RiskLevel.MEDIUM, False
            return Action.ANSWER_WITH_EVIDENCE, Route.KYC_COMPLIANCE, RiskLevel.LOW, False

        if category == Family.PRIVACY:
            if facts.get("legal_hold_is_active") or facts.get("erasure_request_covers_held_records"):
                return Action.ROUTE_PRIVACY_REVIEW, Route.PRIVACY_DPO, RiskLevel.HIGH, False
            if facts.get("erasure_request_received") and facts.get("requester_identity_is_unverified"):
                return Action.ASK_CLARIFICATION, Route.PRIVACY_DPO, RiskLevel.MEDIUM, True
            if not normalized.requester_authenticated or facts.get("legal_hold") or facts.get("sensitive_attachment"):
                return Action.ROUTE_PRIVACY_REVIEW, Route.PRIVACY_DPO, RiskLevel.HIGH, False
            if facts.get("right") == "internal_data_request" or normalized.requester_role == "support_agent":
                return Action.ROUTE_PRIVACY_REVIEW, Route.PRIVACY_DPO, RiskLevel.HIGH, False
            if facts.get("identity_status") == "unknown" or (
                facts.get("right") == "portability" and "scope" in facts and facts.get("scope") is None
            ):
                return Action.ASK_CLARIFICATION, Route.PRIVACY_DPO, RiskLevel.MEDIUM, True
            if facts.get("right") in {"rectification", "portability"}:
                return Action.COLLECT_EVIDENCE, Route.PRIVACY_DPO, RiskLevel.MEDIUM, False
            return Action.ANSWER_WITH_EVIDENCE, Route.PRIVACY_DPO, RiskLevel.LOW, False

        if category == Family.AI_COMPLAINT:
            if facts.get("ai_response_contains_financial_data") or facts.get("recipient_does_not_match_account") or facts.get("export_is_blocked_without_authorization"):
                return Action.ROUTE_AI_INCIDENT_REVIEW, Route.AI_GOVERNANCE, RiskLevel.CRITICAL, False
            if facts.get("assistant_made_unsupported_refund_promise") and facts.get("payment_has_open_external_dispute"):
                return Action.ROUTE_AI_INCIDENT_REVIEW, Route.AI_GOVERNANCE, RiskLevel.HIGH, False
            incident, impact = facts.get("incident"), facts.get("customer_impact")
            if incident == "privacy_disclosure":
                return Action.ROUTE_AI_INCIDENT_REVIEW, Route.AI_GOVERNANCE, RiskLevel.CRITICAL, False
            if incident in {"unsupported_refund_promise", "unauthorized_billing_change", "repeated_policy_violation"}:
                return Action.ROUTE_AI_INCIDENT_REVIEW, Route.AI_GOVERNANCE, RiskLevel.HIGH, False
            if incident == "unknown" and (facts.get("conversation_reference") is None or facts.get("ticket_reference") is None):
                return Action.ASK_CLARIFICATION, Route.AI_GOVERNANCE, RiskLevel.MEDIUM, True
            if incident in {"tone_issue", "quality_review"} and impact == "low":
                return Action.COLLECT_EVIDENCE, Route.SUPPORT, RiskLevel.LOW, False
            return Action.COLLECT_EVIDENCE, Route.AI_GOVERNANCE, RiskLevel.MEDIUM, False

        return Action.COLLECT_EVIDENCE, Route.SUPPORT, RiskLevel.MEDIUM, False


class ResponseDraftingAgent:
    def run(self, decision: Decision, findings: list[Finding]) -> DraftResponse:
        supported = [f for f in findings if f.status == FindingStatus.SUPPORTED]
        unresolved = [f for f in findings if f.status in {FindingStatus.UNVERIFIED, FindingStatus.CONTRADICTED}]
        claim_parts = [f.claim for f in supported]
        claims = [ResponseClaim(text=f.claim, finding_refs=[f.finding_id]) for f in supported]
        if unresolved:
            claim_parts.append("Some requested facts could not be verified from the available records.")
            claims.extend(ResponseClaim(text=f.claim, finding_refs=[f.finding_id]) for f in unresolved)
        next_step = {
            Action.COLLECT_EVIDENCE: "The case should remain in evidence collection before any financial action is considered.",
            Action.ROUTE_ACCESS_REVIEW: "The request should be reviewed by the security and access team.",
            Action.ROUTE_KYC_REVIEW: "The request should be reviewed by the KYC compliance team.",
            Action.ROUTE_PRIVACY_REVIEW: "The request should be reviewed by the privacy team.",
            Action.ROUTE_AI_INCIDENT_REVIEW: "The complaint should be reviewed by the AI governance team.",
            Action.DENY_AUTOMATIC_ACTION: "No automatic action may be taken until requester authorization is verified.",
            Action.ASK_CLARIFICATION: "Additional information is required before the case can proceed.",
            Action.ANSWER_WITH_EVIDENCE: "The available evidence supports answering the request.",
            Action.ROUTE_BILLING_REVIEW: "The request should be reviewed by billing operations.",
        }[decision.action]
        message = " ".join([*claim_parts, next_step, *decision.clarification_questions])
        return DraftResponse(task_id=decision.task_id, message=message, claims=claims, commitments=[])
