'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { UrgencyBadge } from '@/components/cases/urgency-badge'
import { Graph2Panel } from '@/components/dispatch/graph2-panel'
import {
  assignCase,
  deleteIncident,
  getCase,
  listTeams,
  recommendCase,
  updateIncidentLocation,
} from '@/lib/api'
import type { CaseDetailResponse, Recommendation, Team } from '@/lib/types'

export function CaseDetailScreen({ caseId }: { caseId: string }) {
  const { user } = useAuth()
  const router = useRouter()
  const [detail, setDetail] = useState<CaseDetailResponse | null>(null)
  const [teams, setTeams] = useState<Team[]>([])
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [locationText, setLocationText] = useState('')
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (!user) {
      return
    }
    void refreshDetail()
  }, [caseId, user])

  async function refreshDetail() {
    if (!user) {
      return
    }
    const [nextDetail, nextTeams] = await Promise.all([getCase(caseId, user), listTeams(user)])
    setDetail(nextDetail)
    setTeams(nextTeams)
    setLocationText(nextDetail.case.location_text)
  }

  async function refreshRecommendations() {
    if (!user) {
      return
    }
    const result = await recommendCase(caseId, user)
    setRecommendations(result.recommendations)
    setMessage(result.unassigned_reason ?? `Generated ${result.recommendations.length} dispatch option(s).`)
  }

  async function confirmTopRecommendation() {
    if (!user || recommendations.length === 0) {
      return
    }
    const first = recommendations[0]
    await assignCase(
      caseId,
      first.volunteer_ids,
      first.resource_allocations,
      user,
      first.team_id,
      first.resource_ids,
    )
    setMessage('Dispatch confirmed and timeline updated.')
    setDetail(await getCase(caseId, user))
  }

  async function confirmLocation() {
    if (!user || !detail) {
      return
    }
    const updated = await updateIncidentLocation(
      caseId,
      {
        location_text: locationText,
        lat: detail.case.geo?.lat ?? null,
        lng: detail.case.geo?.lng ?? null,
        location_confidence: 'EXACT',
      },
      user,
    )
    setDetail(updated)
    setMessage('Location marked as confirmed for dispatch.')
  }

  async function removeIncident() {
    if (!user || deleting) {
      return
    }
    const ok = window.confirm(
      `Remove ${caseId}? This deletes the incident plus its tokens, evidence metadata, duplicate links, recommendations, and dispatch records.`,
    )
    if (!ok) {
      return
    }
    setDeleting(true)
    try {
      await deleteIncident(caseId, user)
      router.push('/command-center')
      router.refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Incident removal failed.')
      setDeleting(false)
    }
  }

  if (!detail) {
    return <div className="text-sm text-slate-400">Loading incident detail...</div>
  }

  const incident = detail.case
  const teamLookup = new Map(teams.map((team) => [team.team_id, team]))
  const mapMarkers = [
    {
      id: incident.case_id,
      label: incident.case_id,
      subtitle: `${incident.urgency} • ${incident.location_text || 'Location pending'}`,
      tone: 'incident' as const,
      point: incident.geo,
    },
    ...recommendations
      .map((recommendation) => {
        const team = recommendation.team_id ? teamLookup.get(recommendation.team_id) : null
        if (!team) {
          return null
        }
        return {
          id: team.team_id,
          label: team.display_name,
          subtitle: `ETA ${recommendation.eta_minutes ?? 'Unknown'} min`,
          tone: 'team' as const,
          point: team.current_geo ?? team.base_geo,
        }
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item)),
  ]

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 border-b border-white/8 pb-5 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Incident detail</p>
          <h1 className="mt-2 text-3xl font-semibold">{incident.case_id}</h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">{incident.raw_input}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <UrgencyBadge urgency={incident.urgency} />
          <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
            {incident.status}
          </span>
          <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
            {incident.location_confidence}
          </span>
          {incident.duplicate_status !== 'NONE' ? (
            <span className="rounded-full border border-rose-400/20 bg-rose-500/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-rose-200">
              {incident.duplicate_status}
            </span>
          ) : null}
          <button
            className="rounded-full border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black disabled:cursor-not-allowed disabled:opacity-60"
            disabled={deleting}
            onClick={() => void removeIncident()}
          >
            {deleting ? 'Removing' : 'Remove'}
          </button>
        </div>
      </header>

      <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-6">
          <TacticalMap title="Incident map and nearest teams" markers={mapMarkers} />

          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Structured extraction</h2>
                <p className="mt-1 text-sm text-slate-400">Gemini output, data quality, and operational notes.</p>
              </div>
              <span className="text-sm text-slate-400">Confidence {incident.extracted_json?.confidence ?? '--'}</span>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <InfoBlock label="Category" value={incident.extracted_json?.category ?? 'Not extracted'} />
              <InfoBlock label="Subcategory" value={incident.extracted_json?.subcategory ?? 'Not extracted'} />
              <InfoBlock label="Location" value={incident.extracted_json?.location_text || 'Missing location'} />
              <InfoBlock
                label="Time to act"
                value={incident.extracted_json?.time_to_act_hours ? `${incident.extracted_json.time_to_act_hours}h` : 'Unknown'}
              />
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-400">{incident.extracted_json?.notes_for_dispatch}</p>
            {incident.extracted_json?.data_quality.needs_followup_questions.length ? (
              <div className="mt-4 rounded-[1.25rem] border border-amber-300/20 bg-amber-300/8 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-amber-100">Follow-up needed</p>
                <ul className="mt-3 grid gap-2 text-sm leading-6 text-amber-50">
                  {incident.extracted_json.data_quality.needs_followup_questions.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <h2 className="text-lg font-semibold">Info tokens and evidence</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {detail.tokens.map((token) => (
                <div key={token.token_id} className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{token.token_type}</p>
                  <p className="mt-2 text-sm font-medium text-stone-100">{token.summary}</p>
                  <p className="mt-2 text-xs text-slate-500">
                    {token.language.toUpperCase()} • {token.confidence.toFixed(2)}
                  </p>
                </div>
              ))}
              {detail.tokens.length === 0 ? (
                <div className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4 text-sm text-slate-500">
                  No info tokens recorded yet.
                </div>
              ) : null}
            </div>
            <div className="mt-4 grid gap-3">
              {detail.evidence_items.map((item) => (
                <div key={item.evidence_id} className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4">
                  <p className="font-semibold text-stone-100">{item.filename}</p>
                  <p className="mt-2 text-sm text-slate-400">
                    {item.content_type} • {item.status}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <h2 className="text-lg font-semibold">Location review</h2>
            <p className="mt-1 text-sm text-slate-400">Confirm vague geocodes before dispatch when needed.</p>
            <input
              className="mt-4 w-full rounded-[1.25rem] border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-stone-100 outline-none"
              value={locationText}
              onChange={(event) => setLocationText(event.target.value)}
            />
            <div className="mt-4 flex items-center gap-3">
              <button
                className="rounded-2xl border border-white/10 px-4 py-3 text-sm font-semibold text-stone-100"
                onClick={() => void confirmLocation()}
              >
                Mark location confirmed
              </button>
              <p className="text-xs text-slate-500">
                Current coordinates: {incident.geo ? `${incident.geo.lat.toFixed(3)}, ${incident.geo.lng.toFixed(3)}` : 'Not resolved'}
              </p>
            </div>
          </div>

          <Graph2Panel caseId={caseId} title="Run Graph 2 dispatch plan" onCommitted={refreshDetail} />

          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">Fallback dispatch options</h2>
                <p className="mt-1 text-sm text-slate-400">Direct matching remains available for debugging; Graph 2 is the primary judge-demo flow.</p>
              </div>
              <button
                className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:border-white/20 hover:text-white"
                onClick={() => void refreshRecommendations()}
              >
                Refresh options
              </button>
            </div>
            <div className="mt-4 grid gap-3">
              {recommendations.map((recommendation) => {
                const team = recommendation.team_id ? teamLookup.get(recommendation.team_id) : null
                return (
                  <div key={`${recommendation.team_id}-${recommendation.match_score}`} className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="font-semibold text-stone-100">{team?.display_name ?? recommendation.team_id ?? 'Suggested team'}</p>
                        <p className="mt-1 text-sm text-slate-400">
                          Match {recommendation.match_score} • ETA {recommendation.eta_minutes ?? 'Unknown'} min
                        </p>
                      </div>
                      <span className="rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                        {recommendation.route_summary?.provider ?? 'fallback'}
                      </span>
                    </div>
                    <p className="mt-3 text-sm text-slate-300">
                      Members {recommendation.volunteer_ids.join(', ') || 'None'} • Resources{' '}
                      {recommendation.resource_allocations.map((item) => item.resource_type).join(', ') || 'None'}
                    </p>
                  </div>
                )
              })}
              {recommendations.length === 0 ? (
                <p className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4 text-sm text-slate-500">
                  Generate dispatch options to compare teams, route ETA, and resource fit.
                </p>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                className="rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={recommendations.length === 0}
                onClick={() => void confirmTopRecommendation()}
              >
                Confirm top dispatch
              </button>
              <p className="text-sm text-slate-400">{message ?? 'Dispatch the highest-ranked option once location is confirmed.'}</p>
            </div>
          </div>

          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <h2 className="text-lg font-semibold">Duplicate watch and timeline</h2>
            <div className="mt-4 grid gap-3">
              {detail.duplicate_candidates.map((duplicate) => (
                <div key={duplicate.link_id} className="rounded-[1.25rem] border border-rose-400/20 bg-rose-500/8 p-4">
                  <p className="text-sm font-semibold text-rose-100">{duplicate.other_case_id}</p>
                  <p className="mt-1 text-sm text-slate-300">
                    Similarity {duplicate.similarity}
                    {duplicate.geo_distance_km !== null ? ` • ${duplicate.geo_distance_km} km` : ''}
                  </p>
                  <p className="mt-2 text-xs uppercase tracking-[0.18em] text-rose-200">{duplicate.decision}</p>
                </div>
              ))}
              {detail.events.map((event) => (
                <div key={event.event_id} className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4">
                  <p className="text-sm font-semibold text-stone-100">{event.event_type}</p>
                  <p className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">{event.actor_uid}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-3 text-sm font-medium text-stone-100">{value}</p>
    </div>
  )
}
