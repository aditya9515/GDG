'use client'

import { useEffect, useMemo, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { BusyOverlay, InlineLoading } from '@/components/shared/loading-state'
import {
  confirmGraph2Batch,
  confirmGraph2BatchCase,
  downloadGraphRunCsv,
  editGraph2BatchCase,
  replanGraph2Batch,
  runGraph2Batch,
} from '@/lib/api'
import { humanizeToken, incidentSummary } from '@/lib/format'
import type {
  BatchDispatchPlan,
  BatchPlanStatus,
  CaseRecord,
  GraphRun,
  PlannedCaseAssignment,
  Recommendation,
  ReservePolicy,
  ReservePolicyMode,
} from '@/lib/types'

type PlannerFilter = 'ALL' | BatchPlanStatus | 'CRITICAL' | 'LEFTOVERS'

const defaultReservePolicy: ReservePolicy = {
  mode: 'minimal',
  min_medical_reserve_teams: 1,
  min_rescue_reserve_teams: 1,
}

export function BatchDispatchPlanner({
  incidents,
  onCommitted,
}: {
  incidents: CaseRecord[]
  onCommitted?: () => Promise<void> | void
}) {
  
  const { user } = useAuth()
  const [run, setRun] = useState<GraphRun | null>(null)
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [filter, setFilter] = useState<PlannerFilter>('ALL')
  const [page, setPage] = useState(1)
  const pageSize = 10
  const [operatorPrompt, setOperatorPrompt] = useState('')
  const [casePrompt, setCasePrompt] = useState('')
  const [reserveMode, setReserveMode] = useState<ReservePolicyMode>('minimal')
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const incidentById = useMemo(() => new Map(incidents.map((item) => [item.case_id, item])), [incidents])
  const batchDraft = useMemo(
    () => run?.drafts.find((draft) => draft.draft_type === 'DISPATCH' && typeof draft.payload.batch_plan === 'object') ?? null,
    [run],
  )
  const batchPlan = batchDraft?.payload.batch_plan as BatchDispatchPlan | undefined
  const plannedCases = batchPlan?.planned_cases ?? []
  const selectedPlan = plannedCases.find((item) => item.case_id === selectedCaseId) ?? plannedCases[0] ?? null
  const selectedIncident = selectedPlan ? incidentById.get(selectedPlan.case_id) : null

  const filteredPlans = useMemo(() => {
    if (!batchPlan) {
      return []
    }
    if (filter === 'ALL') {
      return batchPlan.planned_cases
    }
    if (filter === 'CRITICAL') {
      return batchPlan.planned_cases.filter((item) => incidentById.get(item.case_id)?.urgency === 'CRITICAL')
    }
    if (filter === 'LEFTOVERS') {
      return batchPlan.planned_cases.filter((item) => ['WAITING', 'BLOCKED', 'UNASSIGNED', 'PARTIAL'].includes(item.assignment_status))
    }
    return batchPlan.planned_cases.filter((item) => item.assignment_status === filter)
  }, [batchPlan, filter, incidentById])
  const totalPages = Math.max(1, Math.ceil(filteredPlans.length / pageSize))

  const paginatedPlans = useMemo(() => {
    const start = (page - 1) * pageSize
    return filteredPlans.slice(start, start + pageSize)
  }, [filteredPlans, page])

  const pageButtons = useMemo(() => {
    return Array.from({ length: totalPages }, (_, index) => index + 1)
  }, [totalPages])

  async function planAll() {
    if (!user) {
      return
    }
    setBusyAction('batch-run')
    setMessage(null)
    try {
      const response = await runGraph2Batch(
        {
          case_ids: [],
          filters: {
            status: ['NEW', 'EXTRACTED', 'SCORED', 'NEEDS_REVIEW'],
            urgency: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'],
          },
          planning_mode: 'global',
          include_reserve: reserveMode !== 'none',
          reserve_policy: { ...defaultReservePolicy, mode: reserveMode },
          operator_prompt: operatorPrompt,
        },
        user,
      )
      setRun(response.run)
      const plan = getBatchPlan(response.run)
      setSelectedCaseId(plan?.planned_cases[0]?.case_id ?? null)
      setMessage('Global dispatch plan is ready for review.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not run global dispatch planning.')
    } finally {
      setBusyAction(null)
    }
  }

  async function replanAll() {
    if (!user || !run) {
      return
    }
    setBusyAction('replan')
    setMessage(null)
    try {
      const response = await replanGraph2Batch(run.run_id, user, {
        operator_prompt: operatorPrompt,
        reserve_policy: { ...defaultReservePolicy, mode: reserveMode },
      })
      setRun(response.run)
      const plan = getBatchPlan(response.run)
      setSelectedCaseId((current) => current ?? plan?.planned_cases[0]?.case_id ?? null)
      setMessage('Global plan recalculated with updated constraints.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not replan globally.')
    } finally {
      setBusyAction(null)
    }
  }

  async function editSelected(prompt: string, fieldUpdates: Record<string, unknown> = {}) {
    if (!user || !run || !selectedPlan) {
      return
    }
    setBusyAction(`case-${selectedPlan.case_id}`)
    setMessage(null)
    try {
      const response = await editGraph2BatchCase(run.run_id, selectedPlan.case_id, user, {
        prompt,
        field_updates: fieldUpdates,
      })
      setRun(response.run)
      setSelectedCaseId(selectedPlan.case_id)
      setCasePrompt('')
      setMessage(`Updated plan for ${selectedPlan.case_id}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not edit selected case plan.')
    } finally {
      setBusyAction(null)
    }
  }

  async function confirmSelected() {
    if (!user || !run || !selectedPlan) {
      return
    }
    setBusyAction('confirm-case')
    setMessage(null)
    try {
      const response = await confirmGraph2BatchCase(run.run_id, selectedPlan.case_id, user)
      setRun(response.run)
      setMessage(`Committed dispatch for ${selectedPlan.case_id}.`)
      await onCommitted?.()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not confirm selected case.')
    } finally {
      setBusyAction(null)
    }
  }

  async function confirmBatch() {
    if (!user || !run) {
      return
    }
    setBusyAction('confirm-batch')
    setMessage(null)
    try {
      const response = await confirmGraph2Batch(run.run_id, user)
      setRun(response.run)
      setMessage('Committed all assigned and partial dispatches.')
      await onCommitted?.()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not confirm batch dispatches.')
    } finally {
      setBusyAction(null)
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

  useEffect(() => {
    setPage(1)
  }, [filter, run])

  return (
    <section className="surface-card relative p-3 sm:p-4">
      <BusyOverlay
        active={Boolean(busyAction)}
        title="Updating global dispatch plan"
        message="Checking open cases, available teams, resources, reserves, and assignment conflicts."
      />
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Global dispatch</p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.04em] text-white sm:text-2xl">Batch dispatch planning</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Plan every open case together so scarce teams, volunteers, and inventory are allocated by global priority instead of one incident at a time.
          </p>
          {message ? <p className="mt-2 text-sm text-slate-200">{message}</p> : null}
        </div>
        <div className="grid w-full gap-2 xl:w-[360px]">
          <select
            className="rounded-xl border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none focus:border-white/25"
            value={reserveMode}
            onChange={(event) => setReserveMode(event.target.value as ReservePolicyMode)}
          >
            <option value="minimal">Minimal reserve</option>
            <option value="none">No reserve</option>
            <option value="custom">Custom reserve defaults</option>
          </select>
          <textarea
            className="min-h-20 rounded-xl border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Optional global instruction, e.g. prioritize flood rescue and maternal transport first..."
            value={operatorPrompt}
            onChange={(event) => setOperatorPrompt(event.target.value)}
          />
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <button
              className="rounded-xl light-surface px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] disabled:opacity-50"
              disabled={Boolean(busyAction)}
              onClick={() => void planAll()}
            >
              {busyAction === 'batch-run' ? <InlineLoading label="Planning" /> : 'Plan all open cases'}
            </button>
            {run ? (
              <button
                className="rounded-xl border border-border px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50"
                disabled={Boolean(busyAction)}
                onClick={() => void replanAll()}
              >
                {busyAction === 'replan' ? <InlineLoading label="Replanning" /> : 'Replan all'}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {batchPlan ? (
        <div className="mt-4 grid gap-2 xl:grid-cols-[0.8fr_1.25fr_0.75fr]">
          <div className="min-w-0 rounded-2xl border border-white/10 bg-black/30 p-3">
            <div className="flex flex-wrap gap-1.5">
              {(['ALL', 'ASSIGNED', 'PARTIAL', 'WAITING', 'BLOCKED', 'UNASSIGNED', 'CRITICAL', 'LEFTOVERS'] as PlannerFilter[]).map((item) => (
                <button
                  key={item}
                  className={`rounded-xl border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] transition ${
                    filter === item ? 'light-surface' : 'border-border text-muted-foreground hover:bg-muted hover:text-foreground'
                  }`}
                  onClick={() => setFilter(item)}
                >
                  {humanizeToken(item)}
                </button>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {pageButtons.map((pageNumber) => (
                <button
                  key={pageNumber}
                  className={`rounded-xl border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] transition ${
                    page === pageNumber
                      ? 'light-surface'
                      : 'border-border text-muted-foreground hover:bg-muted hover:text-foreground'
                  }`}
                  onClick={() => setPage(pageNumber)}
                >
                  {pageNumber}
                </button>
              ))}
            </div>
            <div className="mt-3 grid max-h-[360px] gap-2 overflow-y-auto pr-1 xl:max-h-[620px]">
              {paginatedPlans.map((plan) => {
                const incident = incidentById.get(plan.case_id)
                const active = selectedPlan?.case_id === plan.case_id
                return (
                  <button
                    key={plan.case_id}
                    className={`rounded-2xl border p-3 text-left transition ${
                      active ? 'light-surface' : 'border-white/10 bg-white/[0.025] text-white hover:border-white/25'
                    }`}
                    onClick={() => setSelectedCaseId(plan.case_id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold uppercase tracking-[0.18em]">#{plan.priority_rank}</span>
                      <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.14em] ${active ? 'border-white/25 text-slate-200' : 'border-white/10 text-slate-400'}`}>
                        {humanizeToken(plan.assignment_status)}
                      </span>
                    </div>
                    <p className="mt-2 truncate font-semibold">{plan.case_id}</p>
                    <p className={`mt-1 text-xs ${active ? 'text-slate-300' : 'text-slate-500'}`}>
                      {humanizeToken(incident?.urgency ?? 'UNKNOWN')} | Score {Math.round(plan.planning_priority_score * 100)}%
                    </p>
                    <p className={`mt-2 line-clamp-2 text-xs leading-5 ${active ? 'text-slate-300' : 'text-slate-400'}`}>
                      {incidentSummary(incident)}
                    </p>
                  </button>
                )
              })}
              {filteredPlans.length === 0 ? (
                <p className="rounded-2xl border border-dashed border-white/10 p-4 text-sm text-slate-500">No cases match this planning filter.</p>
              ) : null}
            </div>
          </div>

          <div className="min-w-0 rounded-2xl border border-white/10 bg-black/30 p-3 sm:p-4">
            {selectedPlan ? (
              <SelectedCasePlan
                plan={selectedPlan}
                incident={selectedIncident ?? null}
                busy={Boolean(busyAction)}
                casePrompt={casePrompt}
                onCasePromptChange={setCasePrompt}
                onApplyPrompt={() => void editSelected(casePrompt)}
                onMarkWaiting={() => void editSelected('Move this case to waiting.', { assignment_status: 'WAITING' })}
                onPromote={() => void editSelected('Promote this case to top priority.')}
                onUseAlternative={(recommendation) => void editSelected('Use operator-selected alternative recommendation.', {
                  selected_recommendation: recommendation,
                  assignment_status: 'ASSIGNED',
                })}
                onConfirm={() => void confirmSelected()}
              />
            ) : (
              <p className="text-sm text-slate-500">Run global planning to inspect an assignment.</p>
            )}
          </div>

          <div className="min-w-0 rounded-2xl border border-white/10 bg-black/30 p-3 sm:p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Global summary</p>
            <h3 className="mt-2 text-xl font-semibold text-white">{batchPlan.stats.total_cases} cases evaluated</h3>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <SummaryTile label="Assigned" value={batchPlan.stats.assigned_count} />
              <SummaryTile label="Partial" value={batchPlan.stats.partial_count} />
              <SummaryTile label="Waiting" value={batchPlan.stats.waiting_count} />
              <SummaryTile label="Blocked" value={batchPlan.stats.blocked_count} />
              <SummaryTile label="Unassigned" value={batchPlan.stats.unassigned_count} />
              <SummaryTile label="Conflicts" value={batchPlan.stats.conflict_count} />
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-300">{batchPlan.planning_summary}</p>
            <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.025] p-3">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Reserve pool</p>
              <p className="mt-2 text-sm text-slate-300">
                Teams: {batchPlan.reserve_pool_team_ids.join(', ') || 'None retained'}
              </p>
              <p className="mt-1 text-sm text-slate-400">
                Resources: {batchPlan.reserve_pool_resource_ids.join(', ') || 'None retained'}
              </p>
            </div>
            {batchPlan.conflicts.length > 0 ? (
              <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.04] p-3">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Conflicts</p>
                <div className="mt-2 grid gap-1 text-sm text-slate-300">
                  {batchPlan.conflicts.map((conflict) => <p key={conflict}>{cleanOperatorText(conflict)}</p>)}
                </div>
              </div>
            ) : null}
            <div className="mt-4 grid gap-2">
              <button
                className="rounded-xl light-surface px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] disabled:opacity-50"
                disabled={Boolean(busyAction) || run?.status === 'COMMITTED'}
                onClick={() => void confirmBatch()}
              >
                {busyAction === 'confirm-batch' ? <InlineLoading label="Confirming" /> : 'Confirm full batch'}
              </button>
              {run ? (
                <button
                  className="rounded-xl border border-border px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground"
                  onClick={() => void exportCsv()}
                >
                  Export CSV
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-4 rounded-2xl border border-dashed border-white/10 p-6 text-sm text-slate-500">
          No batch plan yet. Use Plan all open cases to allocate teams and resources across the full open queue.
        </div>
      )}
    </section>
  )
}

function SelectedCasePlan({
  plan,
  incident,
  busy,
  casePrompt,
  onCasePromptChange,
  onApplyPrompt,
  onMarkWaiting,
  onPromote,
  onUseAlternative,
  onConfirm,
}: {
  plan: PlannedCaseAssignment
  incident: CaseRecord | null
  busy: boolean
  casePrompt: string
  onCasePromptChange: (value: string) => void
  onApplyPrompt: () => void
  onMarkWaiting: () => void
  onPromote: () => void
  onUseAlternative: (recommendation: Recommendation) => void
  onConfirm: () => void
}) {
  const selected = plan.selected_recommendation
  const canConfirm = ['ASSIGNED', 'PARTIAL'].includes(plan.assignment_status) && Boolean(selected)
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Selected case</p>
          <h3 className="mt-2 break-words text-xl font-semibold tracking-[-0.04em] text-white sm:text-2xl">{plan.case_id}</h3>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            {incidentSummary(incident)}
          </p>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
          {humanizeToken(plan.assignment_status)}
        </span>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-3">
        <SummaryTile label="Global rank" value={plan.priority_rank} />
        <SummaryTile label="Priority" value={`${Math.round(plan.planning_priority_score * 100)}%`} />
        <SummaryTile label="Case score" value={Math.round(plan.priority_score)} />
      </div>

      <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.025] p-3">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Selected assignment</p>
        {selected ? (
          <div className="mt-2 text-sm leading-6 text-slate-300">
            <p>Team {selected.team_id ?? 'Unassigned'} | Match {Math.round(selected.match_score * 100)}% | ETA {selected.eta_minutes ?? 'unknown'} min</p>
            <p>Volunteers: {selected.volunteer_ids.join(', ') || 'None'}</p>
            <p>Resources: {selected.resource_allocations.map((item) => `${humanizeToken(item.resource_type)}${item.quantity ? ` x${item.quantity}` : ''}`).join(', ') || 'None'}</p>
            <p>Route: {humanizeToken(selected.route_summary?.provider ?? 'estimated')} / {humanizeToken(selected.route_summary?.status ?? 'estimated')}</p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No selected assignment for this case.</p>
        )}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <ReasonList title="Reasons" items={plan.reasons} />
        <ReasonList title="Unmet needs" items={plan.unmet_requirements} empty="All known needs covered." />
      </div>

      {plan.alternative_recommendations.length > 0 ? (
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.025] p-3">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Alternatives</p>
          <div className="mt-2 grid gap-2">
            {plan.alternative_recommendations.slice(0, 4).map((recommendation, index) => (
            <div key={`${recommendation.team_id ?? 'team'}-${index}`} className="flex flex-col gap-3 rounded-xl border border-white/10 p-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-slate-300">
                  {recommendation.team_id ?? 'No team'} | {Math.round(recommendation.match_score * 100)}% | ETA {recommendation.eta_minutes ?? 'unknown'}m
                </p>
                <button
                  className="rounded-xl border border-border px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground transition hover:bg-muted hover:text-foreground"
                  disabled={busy}
                  onClick={() => onUseAlternative(recommendation)}
                >
                  Use
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.025] p-3">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Per-case controls</p>
        <textarea
          className="mt-2 min-h-20 w-full rounded-xl border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
          placeholder="Example: exclude TEAM-002, try partial allocation, or move this case to waiting..."
          value={casePrompt}
          onChange={(event) => onCasePromptChange(event.target.value)}
        />
        <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <button className="rounded-xl border border-border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50" disabled={busy || !casePrompt.trim()} onClick={onApplyPrompt}>
            {busy ? <InlineLoading label="Applying" /> : 'Apply case prompt'}
          </button>
          <button className="rounded-xl border border-border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50" disabled={busy} onClick={onPromote}>
            Promote priority
          </button>
          <button className="rounded-xl border border-border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50" disabled={busy} onClick={onMarkWaiting}>
            Mark waiting
          </button>
          <button className="rounded-xl light-surface px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] disabled:opacity-50" disabled={busy || !canConfirm} onClick={onConfirm}>
            {busy ? <InlineLoading label="Confirming" /> : 'Confirm this case'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ReasonList({ title, items, empty = 'None.' }: { title: string; items: string[]; empty?: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-3">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{title}</p>
      <div className="mt-2 grid gap-1 text-sm leading-6 text-slate-300">
        {(items.length ? items : [empty]).map((item) => <p key={item}>{cleanOperatorText(item)}</p>)}
      </div>
    </div>
  )
}

function SummaryTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-3">
      <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold tracking-[-0.05em] text-white sm:text-2xl">{value}</p>
    </div>
  )
}

function getBatchPlan(run: GraphRun): BatchDispatchPlan | null {
  const draft = run.drafts.find((item) => item.draft_type === 'DISPATCH' && typeof item.payload.batch_plan === 'object')
  return (draft?.payload.batch_plan as BatchDispatchPlan | undefined) ?? null
}

function cleanOperatorText(value: string) {
  return value.includes('_') ? value.replace(/_/g, ' ') : value
}
