'use client'

import { useMemo, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { confirmGraph2, downloadGraphRunCsv, resumeGraph2, runGraph2 } from '@/lib/api'
import type { GraphRun, Recommendation, UserQuestion } from '@/lib/types'

type Graph2PanelProps = {
  caseId: string | null
  title?: string
  onCommitted?: () => Promise<void> | void
}

export function Graph2Panel({ caseId, title = 'Graph 2 dispatch plan', onCommitted }: Graph2PanelProps) {
  const { user } = useAuth()
  const [run, setRun] = useState<GraphRun | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const dispatchDraft = useMemo(
    () => run?.drafts.find((draft) => draft.draft_type === 'DISPATCH' && !draft.removed) ?? null,
    [run],
  )
  const recommendations = useMemo(
    () => ((dispatchDraft?.payload.recommendations as Recommendation[] | undefined) ?? []),
    [dispatchDraft],
  )
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
      setMessage(statusMessage(response.run))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not start Graph 2.')
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
      setMessage(statusMessage(response.run))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not resume Graph 2.')
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!user || !run) {
      return
    }
    setBusy(true)
    setMessage(null)
    try {
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
    <section className="border border-white/10 bg-black/35 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Agent dispatch</p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-white">{title}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            {caseId ? `Planning from incident ${caseId}.` : 'Select an incident before planning dispatch.'}
          </p>
          {message ? <p className="mt-2 text-sm text-amber-100">{message}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="border border-white/15 bg-white px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={busy || !caseId}
            onClick={() => void start()}
          >
            {busy && !run ? 'Planning...' : run ? 'Rerun plan' : 'Run Graph 2'}
          </button>
          {run?.status === 'COMMITTED' ? (
            <button
              className="border border-white/15 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black"
              onClick={() => void exportCsv()}
            >
              Export CSV
            </button>
          ) : null}
        </div>
      </div>

      {run ? (
        <div className="mt-4 border border-white/10 bg-white/[0.025] p-3">
          <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <span className="border border-white/10 px-2 py-1">{run.run_id}</span>
            <span className="border border-white/10 px-2 py-1">{run.status}</span>
            <span className="border border-white/10 px-2 py-1">{run.next_action ?? 'review'}</span>
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
            <div className="mt-4 grid gap-3">
              {recommendations.map((recommendation, index) => (
                <article key={`${recommendation.team_id ?? 'team'}-${index}`} className="border border-white/10 bg-black/25 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Option {index + 1}</p>
                      <h3 className="mt-1 font-semibold text-white">{recommendation.team_id ?? 'Unassigned team'}</h3>
                      <p className="mt-2 text-sm text-slate-400">
                        Match {Math.round(recommendation.match_score * 100)}% | ETA{' '}
                        {recommendation.eta_minutes ?? 'unknown'} min | Route{' '}
                        {recommendation.route_summary?.provider ?? 'fallback'}
                      </p>
                    </div>
                    <span className="border border-white/10 px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-400">
                      {recommendation.resource_allocations.length} resources
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-slate-300">
                    Volunteers: {recommendation.volunteer_ids.join(', ') || 'None'} | Resources:{' '}
                    {recommendation.resource_allocations.map((item) => `${item.resource_type}${item.quantity ? ` x${item.quantity}` : ''}`).join(', ') || 'None'}
                  </p>
                  {recommendation.reasons.length > 0 ? (
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {recommendation.reasons.slice(0, 4).map((reason) => (
                        <div key={`${reason.entity_id}-${reason.label}`} className="border border-white/8 bg-white/[0.02] p-2 text-xs text-slate-400">
                          <p className="font-semibold text-slate-200">{reason.label}</p>
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
              {recommendations.length === 0 ? (
                <p className="border border-dashed border-white/10 p-4 text-sm text-slate-500">
                  {String(dispatchDraft?.payload.unassigned_reason ?? 'No feasible dispatch option found.')}
                </p>
              ) : null}
              {run.status === 'WAITING_FOR_CONFIRMATION' ? (
                <button
                  className="w-full border border-white/15 bg-white px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={busy || recommendations.length === 0}
                  onClick={() => void confirm()}
                >
                  {busy ? 'Confirming...' : 'Confirm dispatch'}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
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
    <div className="mt-4 border border-amber-300/25 bg-amber-300/10 p-3">
      <p className="text-xs uppercase tracking-[0.18em] text-amber-100">Supervisor needs input</p>
      <div className="mt-3 grid gap-3">
        {questions.map((question) => (
          <label key={question.question_id} className="block">
            <span className="text-sm text-amber-50">{question.question}</span>
            <input
              className="mt-2 w-full border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder={question.field ?? 'Answer'}
              value={answers[question.question_id] ?? ''}
              onChange={(event) => onChange(question.question_id, event.target.value)}
            />
          </label>
        ))}
      </div>
      <button
        className="mt-3 border border-white/15 bg-white px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:opacity-50"
        disabled={busy || questions.some((question) => question.required && !(answers[question.question_id] ?? '').trim())}
        onClick={onResume}
      >
        {busy ? 'Reevaluating...' : 'Resume graph'}
      </button>
    </div>
  )
}

function statusMessage(run: GraphRun) {
  if (run.status === 'WAITING_FOR_USER') {
    return 'Graph paused for operator input.'
  }
  if (run.status === 'WAITING_FOR_CONFIRMATION') {
    return 'Assignment preview is ready for confirmation.'
  }
  if (run.status === 'COMMITTED') {
    return `Dispatch committed: ${run.committed_record_ids.join(', ') || 'record saved'}.`
  }
  return run.error_message ?? run.status
}

