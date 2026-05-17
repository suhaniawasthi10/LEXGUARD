import { useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function App() {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function analyze() {
    if (!file) { setError('Pick a file first.'); return }
    setError(''); setResult(null); setLoading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`${API_URL}/analyze`, { method: 'POST', body: fd })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setResult(await res.json())
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1>LexGuard</h1>
      <p>Simulated negotiation — not legal advice.</p>
      <div>
        <input type="file" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button onClick={analyze} disabled={loading || !file}>
          {loading ? 'Analyzing...' : 'Analyze'}
        </button>
      </div>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {result && (
        <div>
          <p>
            doc_type: {result.doc_type} | overall_risk_score: {result.overall_risk_score} | red_flag_count: {result.red_flag_count}
          </p>
          <ul>
            {result.clauses.map((c) => (
              <li key={c.id}>
                <p><strong>[{c.severity}] {c.category}</strong></p>
                <p><em>{c.clause_text}</em></p>
                <p>Plain English: {c.plain_english}</p>
                <p>Risk reason: {c.risk_reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
