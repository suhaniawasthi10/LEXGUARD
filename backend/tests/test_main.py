"""LexGuard backend test suite.

Covers the deterministic Python logic (extract_text, compute_score,
COUNTERPARTY_ROLES) directly, and the FastAPI endpoints via TestClient.
All Gemini API calls are mocked — the suite never makes real network
calls to Google.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from main import (
    COUNTERPARTY_ROLES,
    SEVERITY_WEIGHTS,
    app,
    compute_score,
    extract_text,
)


client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health_returns_ok():
    """GET /health returns 200 and a stable shape."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "gemini_configured" in body


# ---------------------------------------------------------------------------
# compute_score — deterministic, no Gemini
# ---------------------------------------------------------------------------

def test_compute_score_empty_clauses():
    """Empty clause list scores 0 and 0 red flags."""
    score, red = compute_score([])
    assert score == 0
    assert red == 0


def test_compute_score_one_red():
    """A single red clause scores 25 and counts 1 red flag."""
    score, red = compute_score([{"severity": "red"}])
    assert score == 25
    assert red == 1


def test_compute_score_mixed_severities():
    """Mixed severities sum correctly (red=25, amber=10, green=0)."""
    clauses = [
        {"severity": "red"},
        {"severity": "amber"},
        {"severity": "green"},
        {"severity": "red"},
    ]
    score, red = compute_score(clauses)
    assert score == 25 + 10 + 0 + 25  # 60
    assert red == 2


def test_compute_score_capped_at_100():
    """Raw weighted total above 100 is capped at 100."""
    clauses = [{"severity": "red"}] * 10  # raw = 250
    score, red = compute_score(clauses)
    assert score == 100
    assert red == 10


def test_compute_score_ignores_unknown_severity():
    """Unknown / missing severity contributes 0 and is not red."""
    clauses = [{"severity": "unknown"}, {"severity": "red"}, {}]
    score, red = compute_score(clauses)
    assert score == 25
    assert red == 1


def test_severity_weights_constants():
    """Severity weights are the contract: red=25, amber=10, green=0."""
    assert SEVERITY_WEIGHTS == {"red": 25, "amber": 10, "green": 0}


# ---------------------------------------------------------------------------
# extract_text — PDF + DOCX
# ---------------------------------------------------------------------------

def test_extract_text_pdf_returns_text():
    """A real PDF fixture extracts non-empty text containing known content."""
    data = (FIXTURES / "sample.pdf").read_bytes()
    text = extract_text("sample.pdf", data)
    assert isinstance(text, str)
    assert len(text) > 0
    assert "LexGuard" in text


def test_extract_text_docx_returns_text():
    """A real DOCX fixture extracts non-empty text containing known content."""
    data = (FIXTURES / "sample.docx").read_bytes()
    text = extract_text("sample.docx", data)
    assert isinstance(text, str)
    assert "LexGuard" in text


def test_extract_text_rejects_unsupported_extension():
    """Unsupported extensions raise HTTPException(400), not a 500."""
    with pytest.raises(HTTPException) as excinfo:
        extract_text("note.txt", b"plain text")
    assert excinfo.value.status_code == 400
    assert "Unsupported" in excinfo.value.detail


# ---------------------------------------------------------------------------
# /analyze — boundary checks (no Gemini call reached)
# ---------------------------------------------------------------------------

def test_analyze_rejects_unsupported_file_type():
    """POST /analyze with a .txt returns a clean 400, not a 500."""
    response = client.post(
        "/analyze",
        files={"file": ("note.txt", b"some text", "text/plain")},
    )
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body
    assert "Unsupported" in body["detail"]


def test_analyze_rejects_empty_file():
    """POST /analyze with a zero-byte payload returns a clean 400."""
    response = client.post(
        "/analyze",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body
    assert "Empty" in body["detail"]


# ---------------------------------------------------------------------------
# COUNTERPARTY_ROLES mapping
# ---------------------------------------------------------------------------

def test_counterparty_role_employment_is_employer():
    """employment doc_type maps to a hiring-manager / employer role."""
    role = COUNTERPARTY_ROLES["employment"]
    assert "hiring manager" in role.lower() or "employer" in role.lower()


def test_counterparty_role_rental_is_landlord():
    """rental doc_type maps to a landlord role."""
    role = COUNTERPARTY_ROLES["rental"]
    assert "landlord" in role.lower()


def test_counterparty_role_vendor_is_vendor():
    """vendor doc_type maps to the vendor's account manager."""
    role = COUNTERPARTY_ROLES["vendor"]
    assert "vendor" in role.lower()


def test_counterparty_role_unknown_falls_back_to_other():
    """An unrecognised doc_type falls back to the generic 'other' role."""
    # The endpoint logic uses .get(doc_type, COUNTERPARTY_ROLES["other"]).
    assert COUNTERPARTY_ROLES.get("not_a_real_type", COUNTERPARTY_ROLES["other"]) == COUNTERPARTY_ROLES["other"]


def test_counterparty_roles_cover_all_doc_types():
    """All declared doc_type values from the analyzer schema have a role."""
    expected = {"employment", "rental", "vendor", "tos", "privacy", "other"}
    assert expected.issubset(set(COUNTERPARTY_ROLES.keys()))


# ---------------------------------------------------------------------------
# /analyze and /negotiate — full path with Gemini mocked
# ---------------------------------------------------------------------------

def _fake_gemini_client(response_text: str) -> MagicMock:
    """Build a MagicMock that mimics genai.Client.models.generate_content."""
    fake = MagicMock()
    fake.models.generate_content.return_value = MagicMock(text=response_text)
    return fake


def test_analyze_full_flow_with_mocked_gemini(monkeypatch):
    """/analyze parses the model's JSON and applies deterministic scoring."""
    fake_json = json.dumps({
        "doc_type": "employment",
        "clauses": [
            {
                "id": 1,
                "category": "non_compete",
                "clause_text": "Sample clause text.",
                "plain_english": "What it means.",
                "severity": "red",
                "risk_reason": "Why it is risky.",
            },
            {
                "id": 2,
                "category": "termination",
                "clause_text": "Standard notice clause.",
                "plain_english": "Plain.",
                "severity": "green",
                "risk_reason": "Low.",
            },
        ],
    })
    monkeypatch.setattr(main, "client", _fake_gemini_client(fake_json))

    data = (FIXTURES / "sample.docx").read_bytes()
    response = client.post(
        "/analyze",
        files={"file": (
            "sample.docx",
            data,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["doc_type"] == "employment"
    assert body["overall_risk_score"] == 25  # one red clause
    assert body["red_flag_count"] == 1
    assert len(body["clauses"]) == 2


def test_negotiate_returns_reply_with_mocked_gemini(monkeypatch):
    """/negotiate returns the model's reply text in the {reply} envelope."""
    monkeypatch.setattr(
        main,
        "client",
        _fake_gemini_client("I hear your concern, but we cannot reduce the duration."),
    )

    response = client.post(
        "/negotiate",
        json={
            "doc_type": "employment",
            "clause": {
                "category": "non_compete",
                "clause_text": "24-month non-compete.",
                "risk_reason": "Too long.",
            },
            "history": [{"role": "user", "content": "Six months is more reasonable."}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "I hear your concern, but we cannot reduce the duration."
