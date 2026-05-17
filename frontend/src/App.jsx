import { useMemo, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const SEVERITY_ORDER = { red: 0, amber: 1, green: 2 }

export default function App() {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

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
                    <button className="ghost" disabled title="Available in the next build">
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
    </div>
  )
}
