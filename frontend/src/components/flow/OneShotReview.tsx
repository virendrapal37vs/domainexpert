import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import {
  flowQueryKeys,
  recordWorkflowTriggerReview,
  type TriggerObservation,
  type Workflow,
} from '@/api/flow'
import { Button } from '@/components/ui/button'
import { showToast } from '@/utils/toast'

const labels: Record<TriggerObservation, string> = {
  order_seen: 'I found an order in my broker account',
  no_order_seen: 'I did not find an order in my broker account',
  uncertain: 'The outcome is still uncertain',
}

export function OneShotReview({ workflowId, isActive, status }: {
  workflowId: number
  isActive: boolean
  status: NonNullable<Workflow['one_shot_status']>
}) {
  const queryClient = useQueryClient()
  const selectId = useId()
  const [observation, setObservation] = useState<TriggerObservation>('uncertain')
  const save = useMutation({
    mutationFn: () => recordWorkflowTriggerReview(workflowId, observation),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflow(workflowId) })
      showToast.success('Review observation saved', 'flow')
    },
    onError: () => showToast.error('Could not save review observation', 'flow'),
  })
  if (status.review) {
    return (
      <p className="mt-2 text-muted-foreground">
        Your saved observation: {labels[status.review.observation]}. This does not confirm broker
        execution or unlock the trigger.
      </p>
    )
  }
  if (status.state !== 'claimed' && status.state !== 'consumed') return null
  if (isActive) {
    return <p className="mt-2 text-muted-foreground">Deactivate this workflow before recording a review.</p>
  }
  return (
    <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={(event) => {
      event.preventDefault()
      save.mutate()
    }}>
      <label htmlFor={selectId}>After checking execution history and broker orders:</label>
      <select id={selectId} value={observation} disabled={save.isPending}
        className="rounded-md border border-input bg-background px-2 py-1"
        onChange={(event) => setObservation(event.target.value as TriggerObservation)}>
        {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <Button type="submit" size="sm" variant="outline" disabled={save.isPending}>
        {save.isPending ? 'Saving…' : 'Save observation'}
      </Button>
      <p className="w-full text-muted-foreground">
        Your observation is recorded once. It does not confirm broker execution or unlock the trigger.
      </p>
    </form>
  )
}
