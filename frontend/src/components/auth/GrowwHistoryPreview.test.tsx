import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { GrowwHistoryPreview } from './GrowwHistoryPreview'

vi.mock('@/api/client', () => ({ fetchCSRFToken: vi.fn(async () => 'csrf-test') }))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('loads manually with CSRF, displays IST candles, clears old rows on failure', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
    status: 'success', date: '2026-10-21', count: 1, message: 'Loaded; trading disabled.',
    candles: [{ timestamp: 1792554300, open: 428.8, high: 430.45, low: 427.1, close: 427.15, volume: 776276 }],
  }) }).mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ status: 'error', message: 'Authentication failed.' }) })
  vi.stubGlobal('fetch', fetcher)
  render(<GrowwHistoryPreview />)
  expect(fetcher).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button'))
  await screen.findByText('428.8')
  expect(screen.getByText('09:15')).toBeTruthy()
  expect(fetcher).toHaveBeenCalledWith('/api/account/brokers/groww/history-preview', expect.objectContaining({ method: 'POST', credentials: 'include', headers: { 'X-CSRFToken': 'csrf-test', Accept: 'application/json' } }))
  fireEvent.click(screen.getByRole('button'))
  await screen.findByText('Authentication failed.')
  expect(screen.queryByRole('table')).toBeNull()
})

it('reports throttling without retrying', async () => {
  const fetcher = vi.fn(async () => ({ status: 429 }))
  vi.stubGlobal('fetch', fetcher)
  render(<GrowwHistoryPreview />)
  fireEvent.click(screen.getByRole('button'))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Too many previews'))
  expect(fetcher).toHaveBeenCalledTimes(1)
})
