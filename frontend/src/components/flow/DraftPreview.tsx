import { useState } from 'react'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'

type Report = { valid: boolean; issues: { path: string; message: string }[]; steps: {node_id: string; type: string}[]; notice: string }
export function DraftPreview({ workflowId }: { workflowId: number }) {
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState<unknown>(null)
  const currentRevision = useFlowWorkflowStore((s) => s.revision())
  async function inspect() {
    const draft = useFlowWorkflowStore.getState()
    setBusy(true); setError(''); setReport(null)
    const captured = draft.revision()
    try {
      const response = await webClient.post<Report>(`/flow/api/workflows/${workflowId}/draft-preview`, { name: draft.name, nodes: draft.nodes, edges: draft.edges })
      setRevision(captured); setReport(response.data)
    } catch { setError('Preview failed. Please try again.') }
    finally { setBusy(false) }
  }
  return <div className="border-b border-border bg-card px-4 py-2 text-sm">
    <Button variant="outline" size="sm" disabled={busy} onClick={inspect}>{busy ? 'Checking…' : 'Validate / Dry-run preview'}</Button>
    {error && <p role="alert">{error}</p>}
    {report && <div aria-live="polite">
      <p>{revision !== currentRevision ? 'Draft changed — validate again.' : report.valid ? 'Graph validation passed.' : 'Graph needs changes.'}</p>
      <p>{report.notice}</p>
      <ul>{report.issues.map((issue, i) => <li key={i}>{issue.path}: {issue.message}</li>)}</ul>
      <ol>{report.steps.map((step) => <li key={step.node_id}>{step.node_id}: {step.type}</li>)}</ol>
    </div>}
  </div>
}
