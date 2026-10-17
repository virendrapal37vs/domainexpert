import { useState } from 'react'
import { fetchCSRFToken } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function OwnGrowwCredentials({ configured, onSaved }: {
  configured: boolean
  onSaved: () => void
}) {
  const [key, setKey] = useState('')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

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
      setMessage('Your Groww credentials are saved. You can connect below.')
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
      <p role="status" aria-live="polite" className="text-sm">{message}</p>
    </form>
  )
}
