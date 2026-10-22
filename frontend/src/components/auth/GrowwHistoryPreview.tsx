import { useState } from 'react'
import { fetchCSRFToken } from '@/api/client'
import { Button } from '@/components/ui/button'

type Candle = { timestamp: number; open: number; high: number; low: number; close: number; volume: number }
type History = { date: string; count: number; candles: Candle[] }

export function GrowwHistoryPreview() {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState<History | null>(null)
  async function load() {
    setBusy(true)
    setHistory(null)
    setMessage('Loading BHEL history from Groww...')
    try {
      const csrf = await fetchCSRFToken()
      const response = await fetch('/api/account/brokers/groww/history-preview', {
        method: 'POST', credentials: 'include',
        headers: { 'X-CSRFToken': csrf, Accept: 'application/json' },
      })
      if (response.status === 429) throw new Error('Too many previews. Please wait before trying again.')
      const result = await response.json()
      if (!response.ok || result.status !== 'success') throw new Error(result.message || 'Could not load history.')
      setHistory(result)
      setMessage(result.message)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load history.')
    } finally {
      setBusy(false)
    }
  }
  return <section className="space-y-2" aria-label="Read-only historical candles">
    <Button type="button" variant="outline" className="w-full" disabled={busy} onClick={load}>
      {busy ? 'Loading history...' : 'Preview BHEL history (read-only)'}
    </Button>
    <p className="text-xs text-muted-foreground">5-minute candles for the previous weekday, using your saved Groww credentials. No broker session is saved.</p>
    <p role="status" aria-live="polite" className="text-sm">{message}</p>
    {history && <div className="overflow-x-auto text-xs">
      <p>{history.date} · {history.count} candles · first 10 shown · times in IST</p>
      <table className="w-full text-right">
        <thead><tr>{['Time (IST)', 'Open', 'High', 'Low', 'Close', 'Volume'].map(label => <th key={label} scope="col" className="p-1">{label}</th>)}</tr></thead>
        <tbody>{history.candles.slice(0, 10).map(row => <tr key={row.timestamp}>
          <td className="p-1">{new Date(row.timestamp * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false })}</td>
          {[row.open, row.high, row.low, row.close, row.volume].map((value, index) => <td key={index} className="p-1">{value}</td>)}
        </tr>)}</tbody>
      </table>
    </div>}
  </section>
}
