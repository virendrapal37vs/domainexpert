import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnGrowwCredentials } from './OwnGrowwCredentials'

vi.mock('@/api/client', () => ({ fetchCSRFToken: vi.fn(async () => 'csrf-value') }))
afterEach(() => vi.unstubAllGlobals())

describe('OwnGrowwCredentials', () => {
  it('sends only the entered credentials with CSRF and clears secrets after save', async () => {
    const onSaved = vi.fn()
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ status: 'success' }) }))
    vi.stubGlobal('fetch', fetcher)
    render(<OwnGrowwCredentials configured={false} onSaved={onSaved} />)
    fireEvent.change(screen.getByLabelText('Your Groww API key'), { target: { value: 'own-key' } })
    fireEvent.change(screen.getByLabelText('Your Groww API secret'), { target: { value: 'own-secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save my credentials' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
    expect(fetcher).toHaveBeenCalledWith('/api/account/brokers/groww', expect.objectContaining({
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': 'csrf-value' },
      body: JSON.stringify({ api_key: 'own-key', api_secret: 'own-secret' }),
    }))
    expect(screen.getByLabelText('Your Groww API key')).toHaveValue('')
    expect(screen.getByLabelText('Your Groww API secret')).toHaveValue('')
  })

  it('shows server rejection and does not enable broker connect', async () => {
    const onSaved = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ message: 'Sign in first' }) })))
    render(<OwnGrowwCredentials configured={false} onSaved={onSaved} />)
    fireEvent.change(screen.getByLabelText('Your Groww API key'), { target: { value: 'key' } })
    fireEvent.change(screen.getByLabelText('Your Groww API secret'), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save my credentials' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Sign in first'))
    expect(onSaved).not.toHaveBeenCalled()
  })
})
