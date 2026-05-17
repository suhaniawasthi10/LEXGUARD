# LexGuard

**AI-powered contract intelligence with a live adversarial negotiation simulator.**

LexGuard analyses legal and quasi-legal documents (employment contracts, ToS, rental agreements, vendor agreements, privacy policies), flags clauses that are harmful, ambiguous, or one-sided, and then — uniquely — lets the user **negotiate against an AI playing the other party in real time**. The contract fights back.

## Live demo

- **App:** https://lexguard-eight.vercel.app
- **API:** https://lexguard-production-ea41.up.railway.app
- **Source:** https://github.com/suhaniawasthi10/LEXGUARD

A bundled sample contract is one click away (`Try a sample contract`) — no upload needed to see the full flow.

## What it does

LexGuard is built around two AI workflows on top of Google's **Gemini 2.5 Flash**:

1. **Analyzer.** Upload a PDF or DOCX. The system extracts text, sends it to Gemini in strict JSON mode, and returns every risk-bearing clause classified by category (IP, termination, liability, data privacy, payment, arbitration, non-compete, renewal, other), with a severity rating (red / amber / green), a plain-English explanation written for a non-lawyer, and a risk reason. An overall risk score (0–100) and red-flag count are computed deterministically in Python — not by the LLM — so the score is reproducible across runs.

2. **Adversarial Negotiation Simulator.** Click `Negotiate this clause` on any red clause and a chat opens with an AI playing the counterparty implied by the document type — the hiring manager for employment contracts, the landlord for leases, the vendor's account manager for vendor agreements, and so on. The counterparty defends its position, concedes reasonable points, and holds firm on things a real counterparty would never give up. The transcript is held in the client; every turn sends the full history to a stateless backend.

3. **Deal Summary.** After negotiating, click `End negotiation` and a third Gemini call summarizes what you asked for, what the counterparty actually conceded, and produces a **redlined clause** — the rewritten clause text reflecting the wins, in formal contract tone.

This goes beyond passive analysis. Most contract tools stop at a report. LexGuard makes the contract argue back, then shows you the redlined outcome.

## Problem statement alignment

LexGuard targets the **AI Rights & Contract Intelligence System** brief and implements features the brief explicitly suggests:

- Clause extraction and classification ✓
- Contract risk scoring (deterministic, severity-weighted) ✓
- **Adversarial legal reasoning workflows ✓** (the negotiation simulator)
- Liability and obligation analysis ✓
- Ambiguity detection (`amber` severity) ✓
- Privacy and compliance analysis (data-privacy category) ✓
- **Multi-agent reasoning ✓** (the analyzer agent and the in-character negotiation agent are distinct AI roles with different prompts, temperatures, and goals)
- **Scenario-based consequence simulation ✓** (live negotiation against an AI counterparty)
- Explainable AI legal insights ✓ (every clause carries a plain-English explanation and a risk reason)
- **Negotiation recommendation systems ✓** (the entire negotiation + redlined deal summary)

The brief explicitly notes teams may use Google proprietary AI models — LexGuard is built on Gemini 2.5 Flash via Google AI Studio.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite, deployed on **Vercel** | Fast cold start, ideal for a single-page demo. |
| Backend | FastAPI (single `main.py`), deployed on **Railway** | Stateless. Three endpoints. No DB needed. |
| LLM | **Google Gemini 2.5 Flash** (`google-genai` SDK) | Full-contract context window, fast for live demo, JSON-mode for structured output. |
| PDF parsing | `pdfplumber` | Pure-Python, reliable for digitally generated PDFs. |
| DOCX parsing | `python-docx` | Standard. |
| State | None on the server. Negotiation transcript lives in the client. | Deliberately stateless: no database, no auth, no vector store. |

## Architecture and methodology

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system architecture, the three AI workflows, the frozen JSON contract, scoring methodology, and design rationale (including what was deliberately *not* built and why).

## Local development

Backend:
```
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=your_key
uvicorn main:app --reload --port 8000
```

Frontend:
```
cd frontend
npm install
npm run dev
```

The frontend reads `VITE_API_URL` (defaults to `http://localhost:8000`).

## Disclaimer

LexGuard is a research and educational prototype. It does not replace legal professionals and does not provide legally binding advice. The simulated negotiation is a reasoning demonstration, not a substitute for counsel.
