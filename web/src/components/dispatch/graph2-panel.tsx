'use client'

import { useMemo, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { BusyOverlay, InlineLoading } from '@/components/shared/loading-state'
import { SectionCard } from '@/components/shared/mono-ui'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { confirmGraph2, downloadGraphRunCsv, editGraph2, resumeGraph2, runGraph2 } from '@/lib/api'
import { humanizeToken } from '@/lib/format'
import type { GraphRun, Recommendation, UserQuestion } from '@/lib/types'

type Graph2PanelProps = {
  caseId: string | null
  title?: string
  onCommitted?: () => Promise<void> | void
}

export function Graph2Panel({ caseId, title = 'Focused dispatch plan', onCommitted }: Graph2PanelProps) {
  const { user } = useAuth()
  const [run, setRun] = useState<GraphRun | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [planningPrompt, setPlanningPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const dispatchDraft = useMemo(
    () => run?.drafts.find((draft) => draft.draft_type === 'DISPATCH' && !draft.removed) ?? null,
    [run],
  )
  const recommendations = useMemo(
    () => ((dispatchDraft?.payload.ranked_recommendations as Recommendation[] | undefined) ?? (dispatchDraft?.payload.recommendations as Recommendation[] | undefined) ?? []),
    [dispatchDraft],
  )
  const reserveTeams = useMemo(
    () => ((dispatchDraft?.payload.reserve_teams as Recommendation[] | undefined) ?? []),
    [dispatchDraft],
  )
  const conflicts = useMemo(
    () => ((dispatchDraft?.payload.conflicts as string[] | undefined) ?? []),
    [dispatchDraft],
  )
  const reasoningSummary = String(dispatchDraft?.payload.reasoning_summary ?? '')
  const questions = run?.user_questions ?? []

  async function start() {
    if (!user || !caseId) {
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const response = await runGraph2({ linked_case_id: caseId }, user)
      setRun(response.run)
      setSelectedIndex(0)
      setMessage(statusMessage(response.run))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not start the dispatch plan.')
    } finally {
      setBusy(false)
    }
  }

  async function resume() {
    if (!user || !run) {
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const response = await resumeGraph2(run.run_id, answers, user)
      setRun(response.run)
      setSelectedIndex(0)
      setMessage(statusMessage(response.run))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not resume the dispatch plan.')
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!user || !run || !dispatchDraft) {
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const selected = recommendations[selectedIndex] ?? recommendations[0]
      if (selected) {
        const edited = await editGraph2(run.run_id, 'Select operator-approved recommendation.', dispatchDraft.draft_id, user, {
          selected_plan: selected,
        })
        setRun(edited.run)
      }
      const response = await confirmGraph2(run.run_id, user)
      setRun(response.run)
      setMessage(statusMessage(response.run))
      await onCommitted?.()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not confirm dispatch.')
    } finally {
      setBusy(false)
    }
  }

  async function reevaluatePlan() {
    if (!user || !run || !dispatchDraft || !planningPrompt.trim()) {
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const response = await editGraph2(run.run_id, planningPrompt, dispatchDraft.draft_id, user)
      setRun(response.run)
      setPlanningPrompt('')
      setMessage('Planning prompt applied. Review the updated dispatch preview before confirming.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not reevaluate plan.')
    } finally {
      setBusy(false)
    }
  }

  async function exportCsv() {
    if (!user || !run) {
      return
    }
    try {
      await downloadGraphRunCsv(run.run_id, user)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'CSV export failed.')
    }
  }

  return (
    <section className="relative min-w-0">
      <BusyOverlay
        active={busy}
        title="Updating dispatch plan"
        message="Refreshing recommendations, routes, conflicts, and confirmation state."
      />
      <SectionCard
        eyebrow="Agent dispatch"
        title={title}
        description={
          <>
            <p>{caseId ? `Planning from incident ${caseId}.` : 'Select an incident before planning dispatch.'}</p>
            {message ? <p className="mt-2 text-foreground">{message}</p> : null}
          </>
        }
        about="Focused dispatch planning recommends teams and resources for one selected case. Use it when you intentionally want a single-case plan; use the batch board when multiple open cases compete for the same assets."
        action={
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap">
            <Button
              className="uppercase tracking-[0.14em]"
              disabled={busy || !caseId}
              onClick={() => void start()}
            >
              {busy && !run ? <InlineLoading label="Planning" /> : run ? 'Rerun plan' : 'Create dispatch plan'}
            </Button>
            {run?.status === 'COMMITTED' ? (
              <Button
                className="uppercase tracking-[0.14em]"
                variant="outline"
                onClick={() => void exportCsv()}
              >
                Export CSV
              </Button>
            ) : null}
          </div>
        }
      >

      {run ? (
        <div className="rounded-2xl border border-border bg-muted/30 p-3">
          <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            <span className="rounded-full border border-border bg-background px-2 py-1">{humanizeToken(run.status)}</span>
            <span className="rounded-full border border-border bg-background px-2 py-1">{humanizeToken(run.next_action ?? 'review')}</span>
          </div>

          {questions.length > 0 && run.status === 'WAITING_FOR_USER' ? (
            <QuestionBlock
              questions={questions}
              answers={answers}
              busy={busy}
              onChange={(questionId, value) => setAnswers((current) => ({ ...current, [questionId]: value }))}
              onResume={() => void resume()}
            />
          ) : null}

          {run.status === 'WAITING_FOR_CONFIRMATION' || run.status === 'COMMITTED' ? (
            <div className="mt-4 grid min-w-0 gap-3">
              {reasoningSummary ? (
                <div className="rounded-2xl border border-border bg-background/70 p-3 text-sm leading-6 text-foreground">
                  <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Planner reasoning</p>
                  <p className="mt-2">{reasoningSummary}</p>
                </div>
              ) : null}
              {conflicts.length > 0 ? (
                <div className="rounded-2xl border border-foreground/30 bg-foreground/[0.06] p-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Conflicts and warnings</p>
                  <div className="mt-2 grid gap-1 text-sm text-foreground">
                    {conflicts.slice(0, 8).map((conflict) => <p key={conflict}>{conflict}</p>)}
                  </div>
                </div>
              ) : null}
              {recommendations.map((recommendation, index) => (
                <article
                  key={`${recommendation.team_id ?? 'team'}-${index}`}
                  className={`min-w-0 rounded-2xl border p-3 transition ${
                    selectedIndex === index ? 'light-surface' : 'border-border bg-background/70 text-foreground'
                  }`}
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <p className="text-xs uppercase tracking-[0.18em] opacity-70">
                        Option {index + 1} {selectedIndex === index ? '| selected' : ''}
                      </p>
                      <h3 className="mt-1 font-semibold">{recommendation.team_id ?? 'Unassigned team'}</h3>
                      <p className="mt-2 text-sm opacity-75">
                        Match {Math.round(recommendation.match_score * 100)}% | ETA{' '}
                        {recommendation.eta_minutes ?? 'unknown'} min | Route{' '}
                        {humanizeToken(recommendation.route_summary?.provider ?? 'estimated')} / {humanizeToken(recommendation.route_summary?.status ?? 'estimated')}
                      </p>
                    </div>
                    <Button
                      variant={selectedIndex === index ? 'secondary' : 'outline'}
                      size="sm"
                      className="uppercase tracking-[0.14em]"
                      onClick={() => setSelectedIndex(index)}
                    >
                      Select
                    </Button>
                    <span className="rounded-full border border-current/20 px-2 py-1 text-[11px] uppercase tracking-[0.16em] opacity-75">
                      {recommendation.resource_allocations.length} resources
                    </span>
                  </div>
                  <p className="mt-3 break-words text-sm leading-6 opacity-80">
                    Volunteers: {recommendation.volunteer_ids.join(', ') || 'None'} | Resources:{' '}
                    {recommendation.resource_allocations.map((item) => `${humanizeToken(item.resource_type)}${item.quantity ? ` x${item.quantity}` : ''}`).join(', ') || 'None'}
                  </p>
                  {recommendation.reasons.length > 0 ? (
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {recommendation.reasons.slice(0, 4).map((reason) => (
                        <div key={`${reason.entity_id}-${reason.label}`} className="rounded-xl border border-current/15 bg-background/30 p-2 text-xs">
                          <p className="font-semibold">{reason.label}</p>
                          <p className="mt-1">
                            Fit {Math.round(reason.capability_fit * 100)}% | ETA {Math.round(reason.eta_score * 100)}% | Load{' '}
                            {Math.round(reason.workload_balance * 100)}%
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
              {reserveTeams.length > 0 ? (
                <div className="rounded-2xl border border-border bg-background/70 p-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Reserve teams</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {reserveTeams.map((reserve) => (
                      <span key={reserve.recommendation_id ?? reserve.team_id ?? Math.random()} className="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground">
                        {reserve.team_id ?? 'reserve'} | ETA {reserve.eta_minutes ?? 'unknown'}m
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {recommendations.length === 0 ? (
                <p className="rounded-2xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                  {String(dispatchDraft?.payload.unassigned_reason ?? 'No feasible dispatch option found.')}
                </p>
              ) : null}
              {run.status === 'WAITING_FOR_CONFIRMATION' ? (
                <div className="rounded-2xl border border-border bg-background/70 p-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Operator constraints</p>
                  <Textarea
                    className="mt-2 min-h-20"
                    placeholder="Example: keep one ambulance team in reserve, avoid district border crossing..."
                    value={planningPrompt}
                    onChange={(event) => setPlanningPrompt(event.target.value)}
                  />
                  <Button
                    className="mt-2 w-full uppercase tracking-[0.14em] sm:w-auto"
                    variant="outline"
                    disabled={busy || !planningPrompt.trim()}
                    onClick={() => void reevaluatePlan()}
                  >
                    {busy ? <InlineLoading label="Reevaluating" /> : 'Reevaluate plan'}
                  </Button>
                </div>
              ) : null}
              {run.status === 'WAITING_FOR_CONFIRMATION' ? (
                <Button
                  className="w-full uppercase tracking-[0.14em]"
                  disabled={busy || recommendations.length === 0}
                  onClick={() => void confirm()}
                >
                  {busy ? <InlineLoading label="Confirming" /> : 'Confirm dispatch'}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
      </SectionCard>
    </section>
  )
}

function QuestionBlock({
  questions,
  answers,
  busy,
  onChange,
  onResume,
}: {
  questions: UserQuestion[]
  answers: Record<string, string>
  busy: boolean
  onChange: (questionId: string, value: string) => void
  onResume: () => void
}) {
  return (
    <div className="mt-4 rounded-2xl border border-foreground/30 bg-foreground/[0.06] p-3">
      <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Supervisor needs input</p>
      <div className="mt-3 grid gap-3">
        {questions.map((question) => (
          <label key={question.question_id} className="block">
            <span className="text-sm text-foreground">{question.question}</span>
            <Input
              className="mt-2"
              placeholder={question.field ?? 'Answer'}
              value={answers[question.question_id] ?? ''}
              onChange={(event) => onChange(question.question_id, event.target.value)}
            />
          </label>
        ))}
      </div>
      <Button
        className="mt-3 uppercase tracking-[0.14em]"
        disabled={busy || questions.some((question) => question.required && !(answers[question.question_id] ?? '').trim())}
        onClick={onResume}
      >
        {busy ? <InlineLoading label="Reevaluating" /> : 'Resume planning'}
      </Button>
    </div>
  )
}

function statusMessage(run: GraphRun) {
  if (run.status === 'WAITING_FOR_USER') {
    return 'Planning paused for operator input.'
  }
  if (run.status === 'WAITING_FOR_CONFIRMATION') {
    return 'Assignment preview is ready for confirmation.'
  }
  if (run.status === 'COMMITTED') {
    return `Dispatch committed: ${run.committed_record_ids.join(', ') || 'record saved'}.`
  }
  return run.error_message ?? run.status
}
