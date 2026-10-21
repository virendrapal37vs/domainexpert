import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useState } from 'react'
import { Link, Navigate, Outlet, useLocation } from 'react-router'
import { useAuthStore } from '@/stores/authStore'
import { webClient } from '@/api/client'
import { FullWidthLayout } from './FullWidthLayout'
import { Layout } from './Layout'

const PreviewContext = createContext(false)
export const useFlowEditingPreview = () => useContext(PreviewContext)

export function FlowLayout() {
  const queryClient = useQueryClient()
  const [readyFor, setReadyFor] = useState<string | null>(null)
  const user = useAuthStore((state) => state.user)
  const editor = useLocation().pathname.startsWith('/flow/editor/')
  const config = useQuery({
    queryKey: ['flow-editing-preview-config'],
    queryFn: async () => (await webClient.get('/auth/app-info')).data,
    retry: false,
  })
  useEffect(() => {
    if (!config.data?.flow_editing_preview || !user?.username) return
    let active = true
    queryClient.cancelQueries({ queryKey: ['flow'] }).then(() => {
      queryClient.removeQueries({ queryKey: ['flow'] })
      if (active) setReadyFor(user.username)
    })
    return () => { active = false }
  }, [config.data?.flow_editing_preview, user?.username, queryClient])
  if (config.isPending) return <p className="p-4">Loading…</p>
  if (!config.data?.flow_editing_preview) return editor ? <FullWidthLayout /> : <Layout />
  if (!user?.username) return <Navigate to="/login" replace />
  if (readyFor !== user.username) return <p className="p-4">Loading your workflows…</p>
  return (
    <PreviewContext.Provider value={true}>
      <div className="flex h-screen flex-col bg-background text-foreground">
        <div role="status" className="border-b border-border bg-muted px-4 py-2 text-sm">
          Workflow editing preview. Trading, activation and automation are disabled.
          <Link className="ml-3 underline" to="/broker">Back to account</Link>
        </div>
        <div className={editor ? 'min-h-0 flex-1 overflow-auto' : 'flex-1 overflow-auto p-6'}>
          <Outlet />
        </div>
      </div>
    </PreviewContext.Provider>
  )
}
