import { useState } from 'react'
import { fetchCSRFToken } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function OwnGrowwCredentials({ configured, onSaved, connectionBlocked = false }: {
  configured: boolean
  connectionBlocked?: boolean
  onSaved: () => void
}) {
  const [key, setKey] = useState('')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function checkConnection() {
    setBusy(true)
    setMessage('Checking saved credentials with Groww...')
    try {
      const csrf = await fetchCSRFToken()
      const response = await fetch('/api/account/brokers/groww/check', {
        method: 'POST', credentials: 'include',
        headers: { 'X-CSRFToken': csrf, Accept: 'application/json' },
      })
      if (response.status === 429) throw new Error('Too many checks. Please wait before trying again.')
      const result = await response.json()
      setMessage(result.message || 'Could not complete the connection check.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not complete the connection check.')
    } finally {
      setBusy(false)
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setMessage('')
    try {
      const csrf = await fetchCSRFToken()
      const response = await fetch('/api/account/brokers/groww', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ api_key: key, api_secret: secret }),
      })
      const result = await response.json()
      if (!response.ok || result.status !== 'success') {
        throw new Error(result.message || 'Could not save your credentials')
      }
      setKey('')
      setSecret('')
      setMessage(connectionBlocked ? 'Your Groww credentials are saved. You can run the read-only check below; trading remains disabled.' : 'Your Groww credentials are saved. You can connect below.')
      onSaved()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save your credentials')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={save} className="mb-6 space-y-3">
      <p className="text-sm text-muted-foreground">
        {configured ? 'Your Groww credentials are saved.' : 'Save your own Groww API key and secret to connect.'}
      </p>
      <Label htmlFor="own-groww-key">Your Groww API key</Label>
      <Input id="own-groww-key" type="password" value={key}
        onChange={(event) => setKey(event.target.value)} autoComplete="off" maxLength={4096} required />
      <Label htmlFor="own-groww-secret">Your Groww API secret</Label>
      <Input id="own-groww-secret" type="password" value={secret}
        onChange={(event) => setSecret(event.target.value)} autoComplete="off" maxLength={4096} required />
      <Button type="submit" variant="outline" className="w-full" disabled={busy}>
        {busy ? 'Saving...' : 'Save my credentials'}
      </Button>
      {connectionBlocked && configured && (
        <>
          <Button type="button" variant="outline" className="w-full" disabled={busy}
            onClick={checkConnection}>
            {busy ? 'Please wait...' : 'Check Groww (read-only)'}
          </Button>
          <p className="text-xs text-muted-foreground">Uses saved credentials for authentication and one BHEL quote. Does not save a broker session or enable trading.</p>
        </>
      )}
      <p role="status" aria-live="polite" className="text-sm">{message}</p>
    </form>
  )
}
