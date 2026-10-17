import { useState } from 'react'
import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function Signup() {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const fields = Object.fromEntries(new FormData(event.currentTarget))
    setBusy(true)
    setMessage('')
    try {
      const csrf = await fetch('/auth/csrf-token', { credentials: 'include' })
      if (!csrf.ok) throw new Error('Please refresh and try again.')
      const { csrf_token } = await csrf.json()
      const response = await fetch('/auth/signup', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
        body: JSON.stringify(fields),
      })
      const result = await response.json()
      setMessage(result.message || 'Unable to create account.')
      if (response.ok) setDone(true)
    } catch {
      setMessage('Unable to create account. Please try again.')
    } finally { setBusy(false) }
  }
  return <main className="min-h-screen flex items-center justify-center p-6">
    <section className="w-full max-w-md rounded-xl border p-8 space-y-6 shadow-lg">
      <img src="/images/domainxpert-trade.png" alt="DomainXpert Trade" className="h-16 mx-auto object-contain" />
      <h1 className="text-2xl font-semibold">Create your account</h1>
      {!done && <form onSubmit={submit} className="space-y-4">
        <Label htmlFor="username">Username</Label><Input id="username" name="username" required pattern="[a-z0-9_]{3,40}" autoComplete="username" />
        <p className="text-sm text-muted-foreground">3–40 lowercase letters, numbers or underscores.</p>
        <Label htmlFor="email">Email</Label><Input id="email" name="email" type="email" required maxLength={120} autoComplete="email" />
        <Label htmlFor="password">Password</Label><Input id="password" name="password" type="password" required minLength={8} maxLength={128} autoComplete="new-password" />
        <p className="text-sm text-muted-foreground">Use uppercase, lowercase, a number and a special character (!@#$%^&amp;*).</p>
        <Label htmlFor="confirm_password">Confirm password</Label><Input id="confirm_password" name="confirm_password" type="password" required maxLength={128} autoComplete="new-password" />
        <Button className="w-full" disabled={busy}>{busy ? 'Creating account…' : 'Sign up'}</Button>
      </form>}
      {message && <p role="status">{message}</p>}
      <p>Already have an account? <Link to="/login" className="text-primary underline">Sign in</Link></p>
    </section>
  </main>
}
