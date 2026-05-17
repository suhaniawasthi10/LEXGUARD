"""LexGuard backend — FastAPI service.

Three endpoints, all powered by Google Gemini 2.5 Flash via the
google-genai SDK:

    GEMINI CALL #1  POST /analyze        clause extraction + classification (JSON mode)
    GEMINI CALL #2  POST /negotiate      in-character counterparty, multi-turn
    GEMINI CALL #3  POST /deal-summary   asked / conceded / redlined clause (JSON mode)

The risk score and red-flag count are computed deterministically in
Python (see compute_score) so the same set of classifications always
produces the same score. The server is stateless: the negotiation
transcript lives on the client and is sent in full with every turn.
"""
from __future__ import annotations

import io
import json
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import pdfplumber
from docx import Document

# --- Google Gemini integration --------------------------------------------
# The official Google AI SDK. The Gemini 2.5 Flash model is invoked from
# three places in this file: call_analyzer (clause extraction), the
# /negotiate endpoint (in-character counterparty), and the /deal-summary
# endpoint (redlined clause summary).
from google import genai
from google.genai import types

app = FastAPI(title="LexGuard API")

# CORS is intentionally permissive (`*`) for the hackathon demo so the
# Vercel-hosted frontend and any judge's tooling can reach the API
# directly without an origin allow-list. A production deployment would
# narrow `allow_origins` to the real frontend domain(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The Gemini API key is read from the environment only — never hardcoded
# and never logged. On Railway it is supplied via the GEMINI_API_KEY
# variable. If the key is missing, the LLM-backed endpoints return a
# clear 500 instead of crashing at import time.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODEL = "gemini-2.5-flash"


@app.get("/health")
def health() -> dict:
    """Liveness probe.

    Returns a stable JSON shape used by deploy platforms and the test
    suite to confirm the process is up. The `gemini_configured` flag
    tells operators whether the LLM-backed endpoints will function,
    without ever revealing the key itself.
    """
    return {"status": "ok", "gemini_configured": bool(GEMINI_API_KEY)}


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from an uploaded contract.

    Args:
        filename: Original filename. Used only to dispatch by extension.
        data: Raw file bytes.

    Returns:
        The extracted text, stripped of leading/trailing whitespace.

    Raises:
        HTTPException(400): If the extension is not .pdf or .docx.
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        return "\n".join(parts).strip()
    if name.endswith(".docx"):
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or DOCX.")


ANALYZER_PROMPT = """You are a contract risk analyst protecting the person signing this document.

Read the contract text below. Identify every clause that carries risk to the signer — anything that limits their rights, exposes them to liability, gives the other party disproportionate power, hides obligations, or could realistically be exploited against them. Include borderline / ambiguous clauses too.

For each clause produce an object with these fields:
- id: integer starting at 1
- category: one of: IP, termination, liability, data_privacy, payment, arbitration, non_compete, renewal, other
- clause_text: a verbatim excerpt from the contract (do not paraphrase)
- plain_english: 1-2 sentences explaining what this clause means for the signer, written for a non-lawyer
- severity: "red" (clearly harmful or one-sided against the signer), "amber" (ambiguous or borderline), or "green" (standard / low risk but worth surfacing)
- risk_reason: 1-2 sentences explaining why this clause is risky to the signer

Also classify the overall document into one doc_type from: employment, tos, rental, vendor, privacy, other.

Return ONLY a single valid JSON object, no markdown fences, no commentary, matching this exact shape:

{
  "doc_type": "employment | tos | rental | vendor | privacy | other",
  "clauses": [
    {"id": 1, "category": "...", "clause_text": "...", "plain_english": "...", "severity": "red|amber|green", "risk_reason": "..."}
  ]
}

CONTRACT TEXT:
"""


def call_analyzer(text: str) -> dict:
    """GEMINI CALL #1 — clause extraction + classification.

    Sends the contract text to gemini-2.5-flash in strict JSON mode with
    a low temperature for stable classification. Returns the parsed
    JSON document containing doc_type and clauses.

    Raises:
        HTTPException(500): If GEMINI_API_KEY is not configured.
        HTTPException(502): If the model returns non-JSON output.
    """
    if client is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server.")
    # Google Gemini 2.5 Flash — analyzer call.
    response = client.models.generate_content(
        model=MODEL,
        contents=ANALYZER_PROMPT + text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Model returned invalid JSON.")


# The single source of truth for the risk-scoring rubric. Kept as a
# module constant so tests can assert against it.
SEVERITY_WEIGHTS = {"red": 25, "amber": 10, "green": 0}


def compute_score(clauses: list[dict]) -> tuple[int, int]:
    """Compute overall risk score and red-flag count from classified clauses.

    Deterministic by design: the LLM does classification, Python does
    arithmetic. The same clause list always produces the same score.

    Args:
        clauses: Iterable of clause dicts each carrying a "severity" key
            with value "red", "amber", or "green".

    Returns:
        A (score, red_count) tuple where `score` is the severity-weighted
        total capped at 100, and `red_count` is the number of red clauses.
    """
    score = sum(SEVERITY_WEIGHTS.get(c.get("severity", ""), 0) for c in clauses)
    score = min(score, 100)
    red_count = sum(1 for c in clauses if c.get("severity") == "red")
    return score, red_count


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)) -> dict:
    """Analyze an uploaded PDF or DOCX contract.

    Pipeline: read bytes -> extract_text -> Gemini call #1 -> compute_score.

    Args:
        file: A PDF or DOCX upload (multipart/form-data, field name "file").

    Returns:
        The frozen JSON contract: doc_type, overall_risk_score,
        red_flag_count, clauses[].
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    text = extract_text(file.filename or "", data)
    if not text:
        raise HTTPException(status_code=400, detail="Could not extract any text from the file.")
    parsed = call_analyzer(text)
    clauses = parsed.get("clauses", []) or []
    score, red_count = compute_score(clauses)
    return {
        "doc_type": parsed.get("doc_type", "other"),
        "overall_risk_score": score,
        "red_flag_count": red_count,
        "clauses": clauses,
    }


# Counterparty personas indexed by document type. The /negotiate endpoint
# picks one of these to seed the Gemini system instruction, so the
# in-character reply matches who would actually have drafted the contract.
COUNTERPARTY_ROLES = {
    "employment": (
        "You are a hiring manager representing the employer in this negotiation. "
        "You stand by the employment contract your company drafted and want to keep terms favorable to the company, "
        "while not losing a candidate you actually want to hire."
    ),
    "rental": (
        "You are the landlord (or the landlord's property manager). "
        "You stand by the lease as written and want to keep terms favorable to the property owner, "
        "while still closing the deal with this prospective tenant."
    ),
    "vendor": (
        "You are the vendor's account manager. "
        "You stand by the contract your company drafted and want to keep terms favorable to your business, "
        "while not losing this customer."
    ),
    "tos": (
        "You are a policy lead for the platform that wrote these Terms of Service. "
        "You stand by the current terms and want to keep them favorable to the platform, "
        "while addressing this user's concern."
    ),
    "privacy": (
        "You are a data protection lead for the company that wrote this privacy policy. "
        "You stand by the current policy and want to preserve flexibility for the company, "
        "while addressing this user's concern."
    ),
    "other": (
        "You are the counterparty who drafted this contract. "
        "You stand by the current terms and want to keep them favorable to your side, "
        "while still reaching agreement."
    ),
}

NEGOTIATION_RULES = """You are negotiating ONE specific clause with the person being asked to sign this contract.

Stay fully in character as the counterparty. Speak in first person. Do NOT prefix replies with labels like "Counterparty:" or "Me:". Do NOT narrate ("*leans back*"). Do NOT acknowledge that you are an AI.

Negotiate realistically:
- Defend the clause as the other party would defend it.
- If the user makes a fair, reasonable argument, concede small ground.
- If the user is aggressive or makes an unrealistic demand, push back.
- Hold firm on things a real counterparty would never give up.
- Keep replies short: 2-4 sentences, conversational, plain language — not a legal brief."""


@app.post("/negotiate")
async def negotiate(body: dict) -> dict:
    """GEMINI CALL #2 — in-character counterparty, multi-turn.

    Args:
        body: JSON object with keys:
            doc_type: which counterparty persona to assume.
            clause: dict with category, clause_text, risk_reason.
            history: ordered list of {role: 'user'|'counterparty', content}.

    Returns:
        {"reply": "..."} — one new counterparty message.
    """
    if client is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server.")

    doc_type = (body.get("doc_type") or "other").lower()
    clause = body.get("clause") or {}
    history = body.get("history") or []

    role = COUNTERPARTY_ROLES.get(doc_type, COUNTERPARTY_ROLES["other"])
    clause_context = (
        f"The clause under negotiation (category: {clause.get('category', 'other')}):\n"
        f"\"{clause.get('clause_text', '')}\"\n\n"
        f"The other side considers it risky because: {clause.get('risk_reason', '')}"
    )
    system_instruction = f"{role}\n\n{NEGOTIATION_RULES}\n\n{clause_context}"

    if not history:
        contents = [{
            "role": "user",
            "parts": [{"text": "(I have just opened the negotiation on this clause. Greet me briefly in character and invite me to raise my concern.)"}],
        }]
    else:
        contents = []
        for msg in history:
            # Map our (user/counterparty) roles to Gemini's (user/model).
            role_name = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role_name, "parts": [{"text": msg.get("content", "")}]})
        if contents[-1]["role"] != "user":
            contents.append({"role": "user", "parts": [{"text": "(continue)"}]})

    # Google Gemini 2.5 Flash — negotiation call.
    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.8,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return {"reply": (response.text or "").strip()}


DEAL_SUMMARY_PROMPT = """You are summarizing the negotiation that just took place between the signer of a contract and the counterparty who drafted it.

You are given:
- The original clause that was being negotiated
- Why the signer considered it risky
- The full transcript of the back-and-forth

Produce a concise JSON summary with exactly these three fields:
- "asked_for": 1-2 sentences describing what the signer pushed for across the whole conversation (the substantive asks, not turn-by-turn).
- "conceded": 1-2 sentences describing what the counterparty actually agreed to. Concessions only. If they conceded nothing, say so honestly (e.g. "The counterparty did not concede on any material point.").
- "redlined_clause": the rewritten clause text that reflects the concessions the signer actually won. Preserve the formal contract tone (third person, defined terms like "Employee" and "Company" if present in the original). If nothing was conceded, return the original clause text unchanged.

Return ONLY valid JSON in this exact shape, no markdown fences, no commentary:
{"asked_for": "...", "conceded": "...", "redlined_clause": "..."}
"""


@app.post("/deal-summary")
async def deal_summary(body: dict) -> dict:
    """GEMINI CALL #3 — produce the deal summary.

    Args:
        body: JSON with `clause` (category, clause_text, risk_reason) and
            `history` (the full negotiation transcript).

    Returns:
        JSON with keys asked_for, conceded, redlined_clause.
    """
    if client is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server.")

    clause = body.get("clause") or {}
    history = body.get("history") or []
    if not history:
        raise HTTPException(status_code=400, detail="No negotiation history to summarize.")

    transcript = "\n\n".join(
        f"{'Signer' if m.get('role') == 'user' else 'Counterparty'}: {m.get('content', '')}"
        for m in history
    )
    prompt = (
        DEAL_SUMMARY_PROMPT
        + f"\n\nORIGINAL CLAUSE:\n\"{clause.get('clause_text', '')}\"\n\n"
        + f"WHY THE SIGNER CONSIDERED IT RISKY:\n{clause.get('risk_reason', '')}\n\n"
        + f"NEGOTIATION TRANSCRIPT:\n{transcript}"
    )

    # Google Gemini 2.5 Flash — deal-summary call.
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Model returned invalid JSON.")
