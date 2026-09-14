from __future__ import annotations

from typing import Literal, TypedDict


Decision = Literal["approve_in_principle", "request_document", "escalate"]
NarrativeRiskType = Literal["prompt_injection", "fake_tool_output", "none"]
PreauthorisationStatus = Literal["valid", "expired", "not_found"]


class LineItem(TypedDict):
    code: str
    amount: int | float


class ClaimRecord(TypedDict):
    claim_id: str
    member_id: str
    hospital_id: str
    date_of_service: str
    narrative: str
    documents: list[str]
    lines: list[LineItem]


class MemberRecord(TypedDict):
    member_id: str
    name: str
    policy_id: str
    join_date: str


class PolicyExclusion(TypedDict):
    code: str
    rule: str


class PolicyRecord(TypedDict):
    policy_id: str
    product: str
    status: Literal["active", "lapsed"]
    start_date: str
    end_date: str
    annual_limit: int
    used_to_date: int
    exclusions: list[PolicyExclusion]


class PolicyLookupResult(TypedDict):
    member: MemberRecord
    policy: PolicyRecord
    remaining: int


class HospitalRecord(TypedDict):
    hospital_id: str
    name: str
    panel: bool
    country: str


class MatchedClaimRecord(TypedDict):
    claim_id: str
    member_id: str
    hospital_id: str
    date_of_service: str
    lines: list[LineItem]
    decision: str
    decided_on: str


class DuplicateClaimResult(TypedDict):
    is_duplicate: bool
    matched_claim: MatchedClaimRecord | None


class LineCoverageResult(TypedDict):
    code: str
    description: str
    requires_preauth: bool
    excluded: bool
    exclusion_rule: str | None


class PreauthorisationRecord(TypedDict):
    preauth_id: str
    member_id: str
    procedure_code: str
    valid_from: str
    valid_to: str


class PreauthorisationLookupResult(TypedDict):
    status: PreauthorisationStatus
    preauth: PreauthorisationRecord | None


class RequiredDocumentsResult(TypedDict):
    procedure_code: str
    required_documents: list[str]
    attached_documents: list[str]
    missing_documents: list[str]
    all_present: bool


class NarrativeRiskResult(TypedDict):
    risk_detected: bool
    risk_type: NarrativeRiskType
    evidence_span: str | None


class DecisionLetterReceipt(TypedDict):
    sent: Literal[True]
    claim_id: str
    decision: Decision
    lines_resolved: int
    approved_total: int | float
    refused_total: int | float
    trigger: str | None
    missing: list[str] | None
