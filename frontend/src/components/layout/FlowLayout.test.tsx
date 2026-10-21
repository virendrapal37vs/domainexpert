import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'
import { FlowLayout } from './FlowLayout'

const state = vi.hoisted(() => ({ username: 'alice', preview: true }))
vi.mock('@/stores/authStore', () => ({
  useAuthStore: (select: (s: unknown) => unknown) => select({ user: { username: state.username } }),
}))
vi.mock('@/api/client', () => ({
  webClient: { get: vi.fn(async () => ({ data: { flow_editing_preview: state.preview } })) },
}))
vi.mock('./Layout', () => ({ Layout: () => <p>Normal broker layout</p> }))
vi.mock('./FullWidthLayout', () => ({ FullWidthLayout: () => <p>Normal broker editor</p> }))

beforeEach(() => { state.username = 'alice'; state.preview = true })

it('clears account-private Flow cache before mounting a new account outlet', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['flow', 'workflows'], ['previous-account-private'])
  const seen: { owner: string; data: unknown }[] = []
  function Child() {
    const query = useQuery({ queryKey: ['flow', 'workflows'], queryFn: async () => [state.username] })
    seen.push({ owner: state.username, data: query.data })
    return <p>{query.data?.join(',')}</p>
  }
  function App() {
    return <QueryClientProvider client={client}><MemoryRouter initialEntries={['/flow']}>
      <Routes><Route element={<FlowLayout />}><Route path="/flow" element={<Child />} /></Route></Routes>
    </MemoryRouter></QueryClientProvider>
  }
  const view = render(<App />)
  await screen.findByText('alice')
  expect(seen.some((r) => JSON.stringify(r.data)?.includes('previous-account-private'))).toBe(false)
  act(() => { state.username = 'bob'; view.rerender(<App />) })
  await screen.findByText('bob')
  expect(seen.some((r) => r.owner === 'bob' && JSON.stringify(r.data)?.includes('alice'))).toBe(false)
  view.unmount(); client.clear()
})

it('retains the normal broker layout when preview is disabled', async () => {
  state.preview = false
  const client = new QueryClient()
  const view = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/flow']}>
    <Routes><Route element={<FlowLayout />}><Route path="/flow" element={<p>Preview child</p>} /></Route></Routes>
  </MemoryRouter></QueryClientProvider>)
  await waitFor(() => expect(screen.getByText('Normal broker layout')).toBeTruthy())
  expect(screen.queryByText('Preview child')).toBeNull()
  view.unmount(); client.clear()
})
