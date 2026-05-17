# LexGuard — Architecture and Methodology

This document covers the system architecture, the AI workflows, the methodology behind risk scoring, the design decisions made (and deliberately *not* made) for the LexGuard contract intelligence platform.

## 1. System architecture

LexGuard is a stateless two-tier system with a single LLM dependency.

```
                              ┌─────────────────────────────────┐
                              │  User's browser (Vercel-served) │
                              │  React + Vite single-page app   │
                              └────────────────┬────────────────┘
                                               │
                              POST /analyze    │   PDF / DOCX upload
                              POST /negotiate  │   JSON: clause + history
                              POST /deal-summary
                                               ▼
                              ┌─────────────────────────────────┐
                              │  FastAPI backend (Railway)      │
                              │  Single main.py, stateless      │
                              │                                 │
                              │  ┌──────────────────────────┐  │
                              │  │ extract_text()           │  │
                              │  │  PDF  → pdfplumber       │  │
                              │  │  DOCX → python-docx      │  │
                              │  └────────────┬─────────────┘  │
                              │               ▼                 │
                              │  ┌──────────────────────────┐  │
                              │  │ Gemini 2.5 Flash         │  │
                              │  │  (google-genai SDK)      │  │
                              │  └──────────────────────────┘  │
                              │               │                 │
                              │  ┌────────────▼─────────────┐  │
                              │  │ Deterministic Python      │  │
                              │  │ scoring (red/amber/green) │  │
                              │  └──────────────────────────┘  │
                              └─────────────────────────────────┘
```

- **Frontend:** React + Vite, deployed on Vercel. Holds all UI state including negotiation transcripts. Reads `VITE_API_URL` to reach the backend.
- **Backend:** FastAPI, deployed on Railway. Three POST endpoints + one health check. No database. No session. No auth. The negotiation transcript lives in the client and is sent in full with every `/negotiate` and `/deal-summary` request, which means the server can scale horizontally with no shared state.
- **LLM:** Google Gemini 2.5 Flash via Google AI Studio (`google-genai` SDK). One model, three distinct call patterns.

### Why this shape

The brief lists "real-time deployment" as mandatory. A two-tier stateless design is the fastest path to a deployed system that scales: Vercel handles the static frontend with global edge caching, Railway handles the Python backend with one container. Both have zero-config deploys from GitHub.

No database was added because nothing in the product requires persistence. The contract is parsed, classified, and returned in one request; the negotiation history lives in client React state and is re-sent each turn. Adding a database would add a deploy dependency, a schema migration story, and an entire failure mode (DB outages, connection pool exhaustion) for no functional benefit.

## 2. AI workflows

LexGuard uses **three** distinct Gemini 2.5 Flash calls. Each has a different role, prompt, temperature, output format, and quality target. This is a deliberately small AI surface area — the value comes from how the calls are composed, not from a sprawling agent graph.

### Call 1 — Analyzer (`POST /analyze`)

**Role:** "You are a contract risk analyst protecting the person signing this document."

**Input:** the full extracted contract text.

**Output:** JSON in the frozen schema (see §3). The model identifies every risky clause, classifies it into a category, writes a non-lawyer plain-English explanation, assigns a severity (`red | amber | green`), and explains the risk reason. It also identifies the overall `doc_type`.

**Configuration:**
- `response_mime_type="application/json"` — JSON mode, guarantees parseable output
- `temperature=0.2` — high determinism for classification work
- `thinking_config={"thinking_budget": 0}` — Gemini 2.5's deliberation is disabled for the analyzer because the schema is strict and pre-deliberation adds latency without quality gain

**Why this works:** Gemini 2.5 Flash has a context window large enough to hold a full contract in one shot. We do not chunk and we do not retrieve — chunking would split clauses across calls and lose context, retrieval would add infrastructure for no benefit on document sizes this small.

### Call 2 — Negotiation Counterparty (`POST /negotiate`)

**Role:** Picked from `doc_type` — hiring manager for `employment`, landlord for `rental`, vendor account manager for `vendor`, platform policy lead for `tos`, data protection lead for `privacy`, generic counterparty for `other`.

**Input:** `system_instruction` carrying the role + negotiation rules + the clause being negotiated + the original risk reason. `contents` carries the running conversation, with `role: "user"` for the signer's messages and `role: "model"` for prior counterparty replies.

**Output:** one new in-character counterparty message, 2–4 sentences, plain language.

**Configuration:**
- `temperature=0.8` — higher creativity for natural dialogue
- `thinking_config={"thinking_budget": 0}` — short replies do not need deliberation
- Backend is stateless. The full history is sent every turn from the client.

**Negotiation rules enforced via system prompt:**
- Stay fully in character — first person, no labels like "Counterparty:"
- Defend the clause as the other party would
- Concede small, reasonable points
- Push back on aggressive or unrealistic demands
- Hold firm on things a real counterparty would never give up
- Never acknowledge being an AI

### Call 3 — Deal Summary (`POST /deal-summary`)

**Role:** A neutral summarizer of the just-concluded negotiation.

**Input:** the original clause text, the risk reason, the full transcript flattened to "Signer: …" / "Counterparty: …" lines.

**Output:** JSON `{ "asked_for", "conceded", "redlined_clause" }` — what the signer pushed for across the conversation, what the counterparty actually agreed to (concessions only — calls it out honestly if nothing was conceded), and a redlined clause text rewritten to reflect the wins in formal contract tone.

**Configuration:**
- `response_mime_type="application/json"`
- `temperature=0.3` — leaning deterministic but allowing slight phrasing variation in the redlined clause
- `thinking_config={"thinking_budget": 0}`

## 3. The frozen JSON contract

The analyzer's output schema is the single source of truth shared between Gemini, the backend scoring function, and the frontend renderer. It does not change between phases. This is what made parallel frontend/backend development possible.

```json
{
  "doc_type": "employment | tos | rental | vendor | privacy | other",
  "overall_risk_score": 0,
  "red_flag_count": 0,
  "clauses": [
    {
      "id": 1,
      "category": "IP | termination | liability | data_privacy | payment | arbitration | non_compete | renewal | other",
      "clause_text": "verbatim excerpt from the document",
      "plain_english": "what this means for the signer, 1–2 plain sentences",
      "severity": "red | amber | green",
      "risk_reason": "why this clause is risky to the signer"
    }
  ]
}
```

Gemini emits `doc_type` and `clauses`. The backend computes `overall_risk_score` and `red_flag_count` in Python (see §4) and merges them in.

## 4. Risk scoring methodology

The overall risk score is computed deterministically in Python, **not** by the LLM. This was a deliberate decision.

```
weights = { red: 25, amber: 10, green: 0 }
overall_risk_score = min(sum(weights[c.severity] for c in clauses), 100)
red_flag_count     = count(c for c in clauses if c.severity == "red")
```

**Why not let the LLM compute the score?** Because then the same contract analyzed twice could produce different scores, eroding trust. With Python-side scoring, the same set of classified clauses always produces the same score. The LLM does what it is good at — classification and explanation — and the Python layer does what it is good at — deterministic arithmetic.

The choice of weights (red=25, amber=10, green=0) was tuned so that 4 red clauses produce a perceptually severe score (100) and a contract with mostly amber clauses lands in the 30–60 range, matching how a human would intuitively rate severity.

## 5. Document parsing

- **PDF:** `pdfplumber`. Pure-Python, reliable for digitally generated PDFs, no native binary dependencies that break Railway builds.
- **DOCX:** `python-docx`. Standard.
- **Unsupported file types** are rejected at the boundary with a `400 Unsupported file type` error.

**OCR for scanned PDFs is intentionally out of scope** for this build. Adding Tesseract or a hosted OCR API would inflate the deploy footprint and the latency budget for a feature that is not central to the problem statement's *AI reasoning* objective. The mitigation: any digitally-generated PDF (the overwhelming majority of real contracts) works fine.

## 6. The differentiator — adversarial reasoning

The problem statement explicitly lists *"adversarial legal reasoning workflows"*, *"multi-agent reasoning systems"*, *"scenario-based consequence simulation"*, and *"negotiation recommendation systems"* as suggested features. Most contract analysis tools — and most hackathon submissions to this brief — will implement a passive analyzer and stop there. LexGuard goes one step further:

1. The analyzer flags risky clauses.
2. The user can pick any red clause and open an interactive negotiation.
3. Gemini, configured with a role implied by `doc_type`, role-plays the counterparty — defending the clause, conceding fairly, holding firm where appropriate.
4. The user types pushbacks; the AI counterparty replies in character; multi-turn history is threaded correctly through React state and Gemini's `contents` array.
5. When the user is done, a third Gemini call produces a redlined clause reflecting the wins.

This is not summarization. It is the model reasoning adversarially about a real contract, in real time, against a real human user. It directly addresses the brief's call for "intelligent systems capable of identifying contractual risks, reasoning about their practical implications, and presenting insights in an understandable and transparent manner" — and it goes beyond awareness to **agency**: the user does not just learn that a clause is risky, they get a concrete redlined version they could counter-propose.

## 7. Multi-agent framing

The analyzer agent and the negotiation agent are deliberately distinct AI roles:

| Aspect | Analyzer agent | Negotiator agent |
|---|---|---|
| Goal | Protect the signer | Defend the counterparty |
| Temperature | 0.2 (deterministic) | 0.8 (conversational) |
| Output mode | JSON, strict schema | Free-form natural language |
| Stateless? | Yes (single-shot) | Yes per call, but composes multi-turn via re-sent history |
| Persona | Risk analyst on the signer's side | Hiring manager / landlord / vendor / etc. |

They share no prompt, no temperature, no output format. They are two cooperating-but-opposed AI workers on the same artifact — which is the structural definition of a multi-agent system applied to legal reasoning.

## 8. Explainability

Every flagged clause carries:
- The **verbatim** excerpt from the source contract (no paraphrasing — auditable)
- A **plain-English** translation for a non-lawyer
- An explicit **risk reason** stating why this matters to the signer
- A **severity** rating that is functionally meaningful (drives UI color and the negotiation entry-point)

There is no opaque score. Every part of every classification is human-readable. The risk score itself is deterministic arithmetic over those classifications, not a black-box regression.

## 9. Disclaimer and safety

Per the problem statement constraint that the system "is not expected to replace legal professionals or provide legally binding advice", a `Simulated negotiation — not legal advice.` disclaimer is visible in two places: the main page footer and inside every negotiation modal. The negotiator agent is system-prompted to never give legal advice and to never break character to acknowledge being an AI — both safety choices that keep the demo focused and prevent it from drifting into a "lawyer simulator."

## 10. What was deliberately not built

This was a one-day build. Scope was actively defended. The following were *not* added, and the reasoning is part of the architecture:

- **No database.** Nothing requires persistence.
- **No auth.** No user accounts means no user data, no compliance surface, no login UX cost.
- **No vector database / RAG.** Contracts fit in Gemini's context window. RAG would add an indexing pipeline for no information gain.
- **No LangChain or agent framework.** Three plain `client.models.generate_content` calls do the job. A framework would add abstraction overhead and a learning curve cost for zero functional benefit.
- **No OCR for scanned PDFs.** Out of scope for the build window; addressed by the file-type check.
- **No contract comparison engine.** A future direction, but a separate product surface.

Each omission is a deliberate trade in favor of shipping a deployed, polished, end-to-end demo of the core differentiator — the live adversarial negotiation — within one day.

## 11. Tech stack summary

| Layer | Tech | Role |
|---|---|---|
| Frontend | React 19, Vite | SPA, all UI state, multi-turn negotiation transcript |
| Frontend host | Vercel | Static asset hosting, global edge |
| Backend | FastAPI, Uvicorn | Three POST endpoints, one health check, stateless |
| Backend host | Railway | Python container, single instance |
| LLM | Google Gemini 2.5 Flash | Three calls: analyzer, negotiator, deal summary |
| LLM SDK | `google-genai` | Official Google SDK for Gemini |
| PDF parsing | `pdfplumber` | Pure-Python PDF text extraction |
| DOCX parsing | `python-docx` | DOCX text extraction |

## 12. Endpoint reference

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health` | Liveness check. Returns `{"status": "ok", "gemini_configured": bool}`. |
| `POST` | `/analyze` | Multipart upload, file field. Returns the frozen JSON contract. |
| `POST` | `/negotiate` | JSON body `{doc_type, clause, history}`. Returns `{"reply": "..."}`. |
| `POST` | `/deal-summary` | JSON body `{doc_type, clause, history}`. Returns `{asked_for, conceded, redlined_clause}`. |

CORS is open (`allow_origins=["*"]`) for demo simplicity.

---

**Live:** https://lexguard-eight.vercel.app · **Repo:** https://github.com/suhaniawasthi10/LEXGUARD
