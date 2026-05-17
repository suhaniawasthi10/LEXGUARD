import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const SEVERITY_ORDER = { red: 0, amber: 1, green: 2 }

export default function App() {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [negotiation, setNegotiation] = useState(null)
  const [draft, setDraft] = useState('')
  const threadRef = useRef(null)

  const sortedClauses = useMemo(() => {
    if (!result?.clauses) return []
    return [...result.clauses].sort(
      (a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3),
    )
  }, [result])

  async function analyze() {
    if (!file) { setError('Choose a PDF or DOCX first.'); return }
    setError(''); setResult(null); setLoading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`${API_URL}/analyze`, { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      setResult(await res.json())
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }

  function openNegotiation(clause) {
    setNegotiation({
      clause,
      doc_type: result?.doc_type || 'other',
      history: [],
      pending: false,
      error: '',
    })
    setDraft('')
  }

  function closeNegotiation() {
    setNegotiation(null)
    setDraft('')
  }

  async function sendTurn(e) {
    if (e) e.preventDefault()
    const text = draft.trim()
    if (!text || !negotiation || negotiation.pending) return

    const newHistory = [...negotiation.history, { role: 'user', content: text }]
    setNegotiation({ ...negotiation, history: newHistory, pending: true, error: '' })
    setDraft('')

    try {
      const res = await fetch(`${API_URL}/negotiate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doc_type: negotiation.doc_type,
          clause: {
            category: negotiation.clause.category,
            clause_text: negotiation.clause.clause_text,
            risk_reason: negotiation.clause.risk_reason,
          },
          history: newHistory,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const { reply } = await res.json()
      setNegotiation((n) => n ? {
        ...n,
        history: [...newHistory, { role: 'counterparty', content: reply }],
        pending: false,
      } : null)
    } catch (err) {
      setNegotiation((n) => n ? { ...n, pending: false, error: String(err.message || err) } : null)
    }
  }

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [negotiation?.history?.length, negotiation?.pending])

  useEffect(() => {
    if (!negotiation) return
    function onKey(e) { if (e.key === 'Escape') closeNegotiation() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [negotiation])

  return (
    <div className="page">
      <header className="header">
        <h1>LexGuard</h1>
        <p className="subtitle">Contract risk analysis with live counterparty simulation.</p>
      </header>

      <section className="upload">
        <label className="file-picker">
          <input
            type="file"
            accept=".pdf,.docx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <span className={file ? 'file-name' : 'file-empty'}>
            {file ? file.name : 'Choose a PDF or DOCX'}
          </span>
        </label>
        <button className="primary" onClick={analyze} disabled={loading || !file}>
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      {result && (
        <section className="results">
          <div className="summary">
            <span className="doctype">{(result.doc_type || 'other').replace('_', ' ')} contract</span>
            <span className="sep">·</span>
            <span>Risk <strong>{result.overall_risk_score}</strong>/100</span>
            <span className="sep">·</span>
            <span><strong>{result.red_flag_count}</strong> red {result.red_flag_count === 1 ? 'flag' : 'flags'}</span>
          </div>

          {sortedClauses.length === 0 ? (
            <p className="empty">No risky clauses identified.</p>
          ) : (
            <ul className="clauses">
              {sortedClauses.map((c) => (
                <li key={c.id} className={`clause sev-${c.severity}`}>
                  <div className="clause-head">
                    <span className={`dot sev-${c.severity}`} />
                    <span className="cat">{(c.category || 'other').replace('_', ' ')}</span>
                  </div>
                  <p className="plain">{c.plain_english}</p>
                  <blockquote>{c.clause_text}</blockquote>
                  <p className="reason"><span className="reason-label">Why it matters.</span> {c.risk_reason}</p>
                  {c.severity === 'red' && (
                    <button className="ghost" onClick={() => openNegotiation(c)}>
                      Negotiate this clause
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <footer className="footer">Simulated negotiation — not legal advice.</footer>

      {negotiation && (
        <div className="modal" onClick={closeNegotiation}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <header className="modal-head">
              <div className="modal-head-text">
                <div className="cat">Negotiating · {(negotiation.clause.category || 'other').replace('_', ' ')}</div>
                <p className="modal-clause">{negotiation.clause.clause_text}</p>
              </div>
              <button className="close" onClick={closeNegotiation} aria-label="Close">×</button>
            </header>

            <div className="thread" ref={threadRef}>
              {negotiation.history.length === 0 && (
                <p className="thread-empty">Push back on this clause. The counterparty will reply in character.</p>
              )}
              {negotiation.history.map((m, i) => (
                <div key={i} className={`msg ${m.role === 'user' ? 'msg-user' : 'msg-other'}`}>
                  <div className="msg-role">{m.role === 'user' ? 'You' : 'Counterparty'}</div>
                  <div className="msg-body">{m.content}</div>
                </div>
              ))}
              {negotiation.pending && (
                <div className="msg msg-other">
                  <div className="msg-role">Counterparty</div>
                  <div className="msg-body thinking">Thinking…</div>
                </div>
              )}
              {negotiation.error && <div className="thread-error">{negotiation.error}</div>}
            </div>

            <form className="composer" onSubmit={sendTurn}>
              <input
                type="text"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Type your pushback…"
                disabled={negotiation.pending}
                autoFocus
              />
              <button type="submit" className="primary" disabled={negotiation.pending || !draft.trim()}>
                Send
              </button>
            </form>

            <p className="modal-disclaimer">Simulated negotiation — not legal advice.</p>
          </div>
        </div>
      )}
    </div>
  )
}
