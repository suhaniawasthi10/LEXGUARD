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


@app.post("/negotiate")
async def negotiate(body: dict):
    # Phase 0 stub. Real Gemini call lands in Phase 2.
    return {"reply": "I hear your concern, but this clause reflects standard practice across our industry."}
