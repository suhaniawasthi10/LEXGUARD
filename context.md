# LexGuard — Project Context

## What this is

LexGuard is an AI-powered contract intelligence platform built for a one-day solo hackathon (PromptWars). It analyzes legal and quasi-legal documents (employment contracts, ToS, rental agreements, vendor agreements, privacy policies) and flags clauses that are harmful, exploitative, ambiguous, or high-risk to the person signing them.

**The differentiator:** most teams will build a passive analyzer — upload a contract, get a risk report. LexGuard goes one step further. After flagging the risky clauses, the user can open a **live negotiation simulator**: an AI agent role-plays the other party (the employer, landlord, vendor) and the user negotiates against it in real time. The user pushes back on a clause, the in-character counterparty concedes, counters, or holds firm. At the end, the agent produces the redlined clauses the user actually won.

This makes LexGuard a *negotiator*, not just an *analyzer*. The contract fights back.

## Why this angle

The same problem statement is given to ~200 students. "Upload contract, get red flags" will be built dozens of times and judges will be numb to it. The negotiation simulator is differentiated, and it is still fully inside the brief — the problem statement explicitly lists "Negotiation recommendation systems", "Adversarial legal reasoning workflows", and "Multi-agent reasoning systems" as suggested features. Most teams skip these because they are harder. LexGuard makes them the centerpiece.

## Hard constraints — do not violate

- **Build window is 4 hours, solo.** Scope is locked. Build exactly what BUILD_PLAN.md says. Do not add a database, auth, vector DB, LangChain, or OCR.
- **The analyzer is mandatory, not optional.** The problem statement's objectives require clause extraction, classification, severity scoring, and plain-English explanations. The negotiation simulator sits ON TOP of the analyzer — it does not replace it. Phase 0 and Phase 1 build the analyzer. Phase 2 builds the negotiator. Build both.
- **Gemini API calls are limited and purposeful.** Call 1 extracts and classifies clauses. Call 2 is the multi-turn negotiation agent. Nothing else calls the LLM.
- **Deploy early.** A thin version must be live on Vercel + Railway before any AI logic is written. Non-negotiable.
- **The JSON contract is frozen.** The schema in BUILD_PLAN.md is the single source of truth for the analyzer. Never change its shape mid-build.
- **Include a disclaimer in the UI.** The problem statement says the system must not replace legal professionals or give binding advice. A small line ("Simulated negotiation — not legal advice") must appear in the UI.

## Stack (locked)

- Frontend: React + Vite, deployed on Vercel
- Backend: FastAPI (single `main.py`), deployed on Railway
- LLM: Google Gemini 2.5 Flash via Google AI Studio API key (`google-genai` SDK)
- Document parsing: `pdfplumber` for PDF, `python-docx` for DOCX
- No database. Stateless backend. Negotiation history is held in the frontend and sent with each turn.

## Why Gemini and not Groq

The problem statement explicitly says teams may use Google proprietary models, so using Gemini scores points on the "effectiveness of AI tool usage" judging criterion. Gemini 2.5 Flash handles a full contract in one context window with no chunking and is fast enough for a live demo. The API key comes from Google AI Studio (aistudio.google.com), NOT Vertex AI — Vertex needs service-account auth plumbing that wastes time.

## Judging criteria this build targets

1. Creativity / originality — the live negotiation simulator where an AI plays the opposing party.
2. Effectiveness of AI tool usage — visible Gemini reasoning, structured JSON output, a multi-turn in-character agent judges watch respond live.
3. Prototype quality and functionality — clean end-to-end flow, deployed and live.
4. Problem-solving approach — clause extraction + scoring + interactive negotiation, not keyword matching.
5. Demo and presentation clarity — risk score header, color-coded clause cards, and a dynamic live negotiation, not a static report.

## Architecture

```
User uploads PDF/DOCX
        |
   React (Vercel)  --POST /analyze-->  FastAPI (Railway)
        |                                   |
        |                          extract_text()
        |                                   |
        |                          Gemini call 1: extract + classify + score clauses
        |                                   |
        |                          compute risk score in Python
        |                                   |
   render risk report  <----JSON----  return analyzer JSON
        |
   user picks a red clause, clicks "Negotiate"
        |
   React  --POST /negotiate (clause + full message history)-->  FastAPI
        |                                   |
        |                          Gemini call 2: in-character counterparty, multi-turn
        |                                   |
   render counterparty reply  <----------  return reply
        |
   (repeat turns) ... user ends -> optional deal summary
```

Stateless backend. The negotiation transcript lives in the frontend and is sent in full with every `/negotiate` request.

## What "done" looks like

A live Vercel URL where a judge can: upload a real contract, see an overall risk score, red-flag count, and color-coded clause cards with plain-English explanations; then click "Negotiate" on a red clause and have a live back-and-forth with an AI playing the other party — which pushes back and concedes realistically. That is the product.
