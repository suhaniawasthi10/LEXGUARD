# LexGuard — Build Plan

Read CONTEXT.md first. This is the step-by-step plan. Build in phases. Do not jump ahead. Do not add anything not listed here.

LexGuard has two parts: an **analyzer** (Phases 0-1) and a **negotiation simulator** (Phase 2). Both are required. The analyzer is the mandatory core demanded by the problem statement's objectives. The negotiation simulator is the differentiator that sits on top of it.

## The frozen JSON contract (analyzer output)

Gemini call 1 and the frontend depend on this exact shape. Never change it.

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
      "plain_english": "what this means for the signer, one or two plain sentences",
      "severity": "red | amber | green",
      "risk_reason": "why this clause is risky"
    }
  ]
}
```

---

## Phase 0 — Skeleton and deploy

Goal: a thin version live on Vercel + Railway before any AI logic exists. Do not start Phase 1 until a real upload round-trips on the live URLs.

1. Scaffold the frontend: `npm create vite@latest lexguard -- --template react`. Delete boilerplate. `App.jsx` shows the title "LexGuard" and a file `<input>` plus an "Analyze" button.
2. Create the backend: a single `main.py` FastAPI app.
   - `GET /health` returns `{"status": "ok"}`.
   - `POST /analyze` accepts an uploaded file and, for now, returns **hardcoded fake JSON** in the exact frozen schema above (2-3 sample clauses, mixed severities).
   - `POST /negotiate` accepts a JSON body and, for now, returns a hardcoded fake reply string. (Stub it now so the contract exists.)
3. Add CORS middleware to FastAPI allowing all origins.
4. Create `requirements.txt`: `fastapi`, `uvicorn`, `python-multipart`, `pdfplumber`, `python-docx`, `google-genai`.
5. Push frontend and backend to GitHub (one repo, two folders is fine).
6. Deploy backend to Railway. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`. Confirm `/health` responds.
7. Deploy frontend to Vercel. Put the Railway backend URL in a Vite env var (`VITE_API_URL`).
8. Wire the frontend: on "Analyze", POST the file to `${VITE_API_URL}/analyze`, receive the fake JSON, render it as basic clause cards.

**Exit check:** uploading a file on the live Vercel URL shows the fake clauses. Phase 0 done.

---

## Phase 1 — Gemini call 1: the analyzer

Goal: replace the fake analyzer JSON with a real Gemini-powered pipeline.

1. Add the Google AI Studio API key as a Railway environment variable (e.g. `GEMINI_API_KEY`). Never commit it.
2. Write `extract_text(file)`: branch on file extension. PDF → `pdfplumber`. DOCX → `python-docx`. Return one plain text string. Reject unsupported types with a clear error.
3. Write the Gemini call 1 prompt. Make it strict:
   - Role: "You are a contract risk analyst protecting the person signing this document."
   - Task: extract every clause that carries risk to the signer; classify each into a `category`; write `plain_english` for a non-lawyer; assign `severity`; explain `risk_reason`; also identify the overall `doc_type`.
   - Paste the clause schema into the prompt. Instruct it to return ONLY valid JSON, no markdown fences.
4. Use Gemini's JSON mode (`response_mime_type: "application/json"`) so output parses cleanly.
5. Compute `overall_risk_score` and `red_flag_count` in **Python**, not in the prompt. Score = weighted tally of severities (e.g. red = 25, amber = 10, green = 0, capped at 100). `red_flag_count` = number of red clauses. Keeping this deterministic stops the score from drifting between runs.
6. Replace the fake JSON in `/analyze` with: `extract_text` → Gemini call 1 → compute score → return.
7. Redeploy backend. Upload a real contract on the live site; confirm real clauses render.

**Frontend in parallel:** build the real results view — a risk score header showing `overall_risk_score` and `red_flag_count`, then clause cards color-coded by severity, sorted red first. Each card shows category, clause text, plain-English explanation, risk reason. Red cards get a "Negotiate this clause" button (wired in Phase 2).

**Exit check:** real contract → real scored clauses on the live URL. Phase 1 done.

---

## Phase 2 — Gemini call 2: the negotiation simulator (the differentiator)

This is what sets LexGuard apart. The user picks a red clause and negotiates against an AI playing the other party. Build it cleanly; do not over-engineer it.

### Backend — `/negotiate`

1. Request body shape (frozen):
   ```json
   {
     "doc_type": "employment",
     "clause": { "category": "...", "clause_text": "...", "risk_reason": "..." },
     "history": [
       { "role": "user", "content": "..." },
       { "role": "counterparty", "content": "..." }
     ]
   }
   ```
   `history` is the full transcript so far. On the first turn it is empty.
2. Build the Gemini call 2 prompt:
   - Role: the counterparty implied by `doc_type` — for an employment contract, "You are the hiring manager / employer's representative"; for rental, "the landlord"; for vendor, "the vendor's account manager". Pick the role from `doc_type`.
   - Instruction: you are negotiating this specific clause. Stay in character. Defend the clause as the other party would, but negotiate realistically — concede reasonable points, counter aggressive ones, hold firm on things a real counterparty would not give up. Keep replies short (2-4 sentences), conversational, not a legal brief.
   - Provide the clause text and `risk_reason` as context.
   - Append the `history` as the running conversation.
3. The backend is stateless. It receives the full `history` every call, sends it to Gemini, returns the new counterparty reply as `{ "reply": "..." }`.
4. Replace the Phase 0 stub with this real logic. Redeploy.

### Frontend — negotiation panel

1. Clicking "Negotiate this clause" on a red card opens a chat panel (modal or side panel) for that clause.
2. The panel shows the clause text at the top for reference, then a chat thread, then a text input.
3. State: a `history` array of `{role, content}` messages, held in React state for this clause.
4. On send: append the user message to `history`, POST to `/negotiate` with `doc_type`, `clause`, and full `history`, append the returned `reply` as a `counterparty` message.
5. Style user and counterparty messages distinctly. Show a "thinking..." indicator while waiting.
6. Add a small disclaimer line in the panel: "Simulated negotiation — not legal advice."

**Exit check:** on the live site, clicking Negotiate on a red clause opens a chat, the user can type a pushback, and the AI counterparty replies in character — pushing back and conceding realistically across multiple turns. Phase 2 done. **You now have a complete, differentiated, demoable product.**

---

## Phase 3 — Nice-to-haves (only if time remains, in this order)

1. **Deal summary.** An "End negotiation" button that makes one final Gemini call summarizing what the user asked for, what the counterparty conceded, and the resulting redlined clause text. This is a strong closing beat for the demo — add it first if you have time.
2. DOCX support if not already done (~10 min, `python-docx`).
3. Two or three pre-loaded sample contracts selectable from the UI, so the demo never depends on a live upload working.
4. Doc-type-aware tone tweak in the analyzer prompt.
5. Loading states and error handling polish.

**Do NOT add:** OCR, vector DB, RAG, auth, database, user accounts, contract comparison, multi-document support. Out of scope. They will sink the build.

---

## Fallback if the negotiation chat is behind at 3:30

If Phase 2's multi-turn chat is not working by 3:30, drop to the **single-turn consequence simulator** instead: the user asks one question about a red clause ("what happens if I quit after 6 months?") and the AI answers by reasoning over the clause. Same wow factor, single-turn so much lower demo risk. It reuses the same `/negotiate` endpoint with `history` always empty. Do not spend time on both — pick one by 3:30.

---

## Final 45-60 minutes — freeze and rehearse

Stop building features. Lock the code. Then:

1. Pick ONE sample contract that reliably produces a strong result (several red flags, a clause that negotiates well). This is the demo happy path.
2. Run the full flow on the live URL 3+ times: upload → risk report → open negotiation → 3-4 turns. Confirm no crashes, acceptable latency.
3. Rehearse the negotiation turns. Know roughly what you will type so the counterparty's replies land well. Have 2-3 strong pushback lines ready.
4. Make AI usage visible: say out loud that Gemini 2.5 Flash runs two stages — clause extraction and classification first, then a stateful in-character negotiation agent.
5. Have the sample contract ready to upload instantly. Do not type or hunt for files live.
6. If anything is flaky, demo from a pre-loaded sample contract (Phase 3 item 3) — the safety net.

## Demo narrative (the happy path)

"This is a [employment contract]. I upload it — LexGuard's analyzer extracts and classifies every risky clause and scores the document. Risk score [X]/100, [N] red flags. Now here is what makes LexGuard different. Most tools stop at a report. I click 'Negotiate' on this non-compete clause — and now I'm negotiating against an AI playing the employer. I push back: [type a line]. Watch it respond in character — it concedes here, holds firm there, just like a real counterparty. [Do 2-3 turns.] That is not summarization. That is an AI reasoning adversarially about a real contract, live."