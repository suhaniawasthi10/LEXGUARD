import io
import json
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import pdfplumber
from docx import Document
from google import genai
from google.genai import types

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MODEL = "gemini-2.5-flash"


@app.get("/health")
def health():
    return {"status": "ok", "gemini_configured": bool(GEMINI_API_KEY)}


def extract_text(filename: str, data: bytes) -> str:
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
    if client is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server.")
    response = client.models.generate_content(
        model=MODEL,
        contents=ANALYZER_PROMPT + text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Model returned invalid JSON.")


SEVERITY_WEIGHTS = {"red": 25, "amber": 10, "green": 0}


def compute_score(clauses: list[dict]) -> tuple[int, int]:
    score = sum(SEVERITY_WEIGHTS.get(c.get("severity", ""), 0) for c in clauses)
    score = min(score, 100)
    red_count = sum(1 for c in clauses if c.get("severity") == "red")
    return score, red_count


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
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
async def negotiate(body: dict):
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
            role_name = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role_name, "parts": [{"text": msg.get("content", "")}]})
        if contents[-1]["role"] != "user":
            contents.append({"role": "user", "parts": [{"text": "(continue)"}]})

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.8,
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
async def deal_summary(body: dict):
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

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Model returned invalid JSON.")
