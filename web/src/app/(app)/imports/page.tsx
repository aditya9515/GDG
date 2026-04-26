'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { AlertTriangle, CheckCircle2, ClipboardCheck, FileText, Layers3, Sparkles } from 'lucide-react'

import { Graph2Panel } from '@/components/dispatch/graph2-panel'
import { useAuth } from '@/components/providers/auth-provider'
import { BusyOverlay, InlineLoading } from '@/components/shared/loading-state'
import { AboutButton, PageHeader, SectionCard } from '@/components/shared/mono-ui'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import {
  getGraphRun,
  confirmGraph1,
  deleteGraphRun,
  deleteIngestionJob,
  downloadGraphRunCsv,
  editGraph1,
  getAiStatus,
  listIngestionJobs,
  removeGraph1Draft,
  runGraph1,
  runGraph1File,
} from '@/lib/api'
import { csvTextToFile, parseCsvPreview, type CsvPreview } from '@/lib/csv-preview'
import { humanizeToken } from '@/lib/format'
import { parseTags } from '@/lib/form-utils'
import type { AiStatusResponse, DuplicateCandidate, GraphRun, IngestionJob, RecordDraft } from '@/lib/types'

type ImportKind = 'CSV' | 'PDF' | 'IMAGE'
type ImportTarget = 'incidents' | 'teams' | 'resources' | 'mixed'

const targetLabels: Record<ImportTarget, string> = {
  incidents: 'Incidents',
  teams: 'Teams',
  resources: 'Resources',
  mixed: 'Mixed records',
}

const ACTIVE_GRAPH_RUN_KEY = 'imports_active_graph_run_id'

export default function ImportsPage() {
  const { user, isLoading: authLoading, error: authError } = useAuth()
  const [jobs, setJobs] = useState<IngestionJob[]>([])
  const [kind, setKind] = useState<ImportKind>('CSV')
  const [target, setTarget] = useState<ImportTarget>('incidents')
  const [file, setFile] = useState<File | null>(null)
  const [fileInputKey, setFileInputKey] = useState(0)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [manualText, setManualText] = useState('')
  const [graphRun, setGraphRun] = useState<GraphRun | null>(null)
  const [draftIndex, setDraftIndex] = useState(0)
  const [draftPage, setDraftPage] = useState(0)
  const [editPrompts, setEditPrompts] = useState<Record<string, string>>({})
  const [fieldEdits, setFieldEdits] = useState<Record<string, Record<string, string>>>({})
  const [reevaluatingDraftId, setReevaluatingDraftId] = useState<string | null>(null)
  const [csvText, setCsvText] = useState('')
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null)
  const [importStep, setImportStep] = useState<string | null>(null)
  const [aiStatus, setAiStatus] = useState<AiStatusResponse | null>(null)
  const [jobSearch, setJobSearch] = useState('')
  const [planningCaseId, setPlanningCaseId] = useState<string | null>(null)
  const [duplicateCompare, setDuplicateCompare] = useState<{ draft: RecordDraft; candidate: DuplicateCandidate } | null>(null)


  useEffect(() => {
    if (!user) {
      return
    }

    const savedRunId =
      typeof window !== 'undefined'
        ? localStorage.getItem(ACTIVE_GRAPH_RUN_KEY)
        : null

    if (!savedRunId || graphRun) {
      return
    }

    void (async () => {
      try {
        const restoredRun = await getGraphRun(savedRunId, user)

        if (restoredRun.status !== 'COMMITTED') {
          setGraphRun(restoredRun)
        } else {
          localStorage.removeItem(ACTIVE_GRAPH_RUN_KEY)
        }
      } catch {
        localStorage.removeItem(ACTIVE_GRAPH_RUN_KEY)
      }
    })()
  }, [user, graphRun])

  useEffect(() => {
    if (!user) {
      return
    }
    void Promise.all([listIngestionJobs(user, jobSearch), getAiStatus(user)]).then(([nextJobs, status]) => {
      setJobs(nextJobs)
      setAiStatus(status)
    })
  }, [user, jobSearch])

  useEffect(() => {
    if (!graphRun) {
      setDraftIndex(0)
      setDraftPage(0)
      return
    }

    setDraftIndex((current) => Math.min(current, Math.max(graphRun.drafts.length - 1, 0)))
    setDraftPage((current) => {
      const maxPage = Math.max(Math.ceil(graphRun.drafts.length / 10) - 1, 0)
      return Math.min(current, maxPage)
    })
  }, [graphRun])

  const visibleDrafts = graphRun?.drafts.slice(draftPage * 10, draftPage * 10 + 10) ?? []
  const activeDraft =
    graphRun?.drafts[draftIndex] && visibleDrafts.some((draft) => draft.draft_id === graphRun.drafts[draftIndex].draft_id)
      ? graphRun.drafts[draftIndex]
      : visibleDrafts[0] ?? null
  const draftCounts = useMemo(() => summarizeDrafts(graphRun), [graphRun])
  const groupedDrafts = useMemo(() => groupDrafts(graphRun), [graphRun])
  const sourceWarnings = useMemo(
    () => graphRun?.source_artifacts.flatMap((artifact) => artifact.parse_warnings) ?? [],
    [graphRun],
  )
  const draftPageCount = graphRun ? Math.ceil(graphRun.drafts.length / 10) : 0
  const draftPageStart = draftPage * 10 + 1
  const draftPageEnd = graphRun ? Math.min((draftPage + 1) * 10, graphRun.drafts.length) : 0
  const committedIncidentIds = useMemo(
    () => graphRun?.committed_record_ids.filter((id) => id.startsWith('CASE-') || id.startsWith('DR-') || id.startsWith('HE-')) ?? [],
    [graphRun],
  )
  const previewBlockedReason = authLoading
    ? 'Checking your signed-in session...'
    : !user
      ? 'Sign in with Google before generating an editable preview.'
      : !user.active_org_id
        ? 'Select or create an organization before generating an editable preview.'
        : null

  async function refreshJobs() {
    if (!user) {
      return
    }
    setJobs(await listIngestionJobs(user, jobSearch))
  }

  async function submitFilePreview() {
    if (!user) {
      setMessage('Sign in with Google before generating an editable preview.')
      return
    }
    if (!user.active_org_id) {
      setMessage('Select or create an organization before generating an editable preview.')
      return
    }
    if (!file) {
      setMessage('Choose a file before generating an editable preview.')
      return
    }
    setBusy(true)
    setMessage(null)
    setImportStep(`Parsing ${file.name}...`)
    try {
      const uploadFile = kind === 'CSV' && csvText.trim() ? csvTextToFile(csvText, file.name) : file
      const response = await runGraph1File({ kind, target, file: uploadFile }, user, { onProgress: setImportStep })
      setGraphRun(response.run)
      if (typeof window !== 'undefined') {
        localStorage.setItem(ACTIVE_GRAPH_RUN_KEY, response.run.run_id)
      }
      setDraftIndex(0)
      setPlanningCaseId(null)
      setMessage(
        response.run.drafts.length === 0
          ? `No matching data found for ${targetLabels[target]}. Skipped rows are reported in warnings.`
          : `${file.name} produced ${response.run.drafts.length} editable draft${response.run.drafts.length === 1 ? '' : 's'}.`,
      )
      setFile(null)
      setCsvText('')
      setCsvPreview(null)
      setFileInputKey((current) => current + 1)
      await refreshJobs()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Import failed.')
    } finally {
      setImportStep(null)
      setBusy(false)
    }
  }

  async function chooseFile(nextFile: File | null) {
    setFile(nextFile)
    setCsvText('')
    setCsvPreview(null)
    setMessage(null)
    setImportStep(null)
    if (!nextFile || kind !== 'CSV') {
      return
    }
    try {
      const text = await nextFile.text()
      setCsvText(text)
      setCsvPreview(parseCsvPreview(text, 12))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not read CSV preview.')
    }
  }

  function updateCsv(value: string) {
    setCsvText(value)
    setCsvPreview(parseCsvPreview(value, 12))
  }

  async function startManualPreview() {
    if (!user) {
      setMessage('Sign in with Google before generating an editable preview.')
      return
    }
    if (!user.active_org_id) {
      setMessage('Select or create an organization before generating an editable preview.')
      return
    }
    if (!manualText.trim()) {
      setMessage('Enter source text before generating an editable preview.')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const response = await runGraph1({ source_kind: 'MANUAL_TEXT', text: manualText, target }, user)
      setGraphRun(response.run)
      if (typeof window !== 'undefined') {
        localStorage.setItem(ACTIVE_GRAPH_RUN_KEY, response.run.run_id)
      }
      setDraftIndex(0)
      setMessage('Editable preview is ready. Confirm, revise with a prompt, or remove draft data.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Preview generation failed.')
    } finally {
      setBusy(false)
    }
  }

  async function editDraft(draft: RecordDraft) {
    if (!user || !graphRun) {
      return
    }
    const prompt = editPrompts[draft.draft_id]?.trim() ?? ''
    const updates = buildFieldUpdates(draft, fieldEdits[draft.draft_id] ?? {})
    if (!prompt && Object.keys(updates).length === 0) {
      setMessage('Add a prompt or edit at least one structured field before reevaluating.')
      return
    }
    setReevaluatingDraftId(draft.draft_id)
    setMessage(null)
    try {
      const response = await editGraph1(graphRun.run_id, prompt, draft.draft_id, user, updates)
      setGraphRun(response.run)
      setEditPrompts((current) => ({ ...current, [draft.draft_id]: '' }))
      setFieldEdits((current) => ({ ...current, [draft.draft_id]: {} }))
      setMessage('Draft reevaluated. Changed fields are highlighted on the card.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Draft reevaluation failed.')
    } finally {
      setReevaluatingDraftId(null)
    }
  }

  async function removeDraft(draftId: string) {
    if (!user || !graphRun) {
      return
    }
    const response = await removeGraph1Draft(graphRun.run_id, draftId, 'Removed from preview by operator', user)
    setGraphRun(response.run)
  }

  async function confirmPreview() {
    if (!user || !graphRun) {
      return
    }
    setBusy(true)
    try {
      const response = await confirmGraph1(graphRun.run_id, user)
      setGraphRun(response.run)
      if (typeof window !== 'undefined') {
        localStorage.removeItem(ACTIVE_GRAPH_RUN_KEY)
      }

      setMessage(`Preview confirmed. Stored records: ${response.run.committed_record_ids.join(', ') || 'none'}.`)
      await refreshJobs()
    } finally {
      setBusy(false)
    }
  }

  async function downloadCsv() {
    if (!user || !graphRun) {
      return
    }
    try {
      await downloadGraphRunCsv(graphRun.run_id, user)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'CSV export failed.')
    }
  }

  async function clearPreview() {
    if (user && graphRun) {
      try {
        await deleteGraphRun(graphRun.run_id, user)
      } catch {
        // Clearing the local preview should still recover the UI if backend history deletion fails.
      }
    }
    setGraphRun(null)
    setFile(null)
    setFileInputKey((current) => current + 1)
    setCsvText('')
    setCsvPreview(null)
    setEditPrompts({})
    setFieldEdits({})
    setReevaluatingDraftId(null)
    setImportStep(null)
    setMessage('Preview cleared. You can upload the same file again.')
    setPlanningCaseId(null)

    if (typeof window !== 'undefined') {
      localStorage.removeItem(ACTIVE_GRAPH_RUN_KEY)
    }
  }

  async function removeJob(jobId: string) {
    if (!user) {
      return
    }
    const ok = window.confirm('Remove this import job and generated artifacts tracked by the job?')
    if (!ok) {
      return
    }
    await deleteIngestionJob(jobId, user)
    setJobs((current) => current.filter((job) => job.job_id !== jobId))
  }

  function jumpNextUnresolved() {
    if (!graphRun) {
      return
    }
    const next = graphRun.drafts.findIndex((draft, index) => index > draftIndex && isUnresolved(draft))
    if (next >= 0) {
      setDraftIndex(next)
      return
    }
    const first = graphRun.drafts.findIndex(isUnresolved)
    if (first >= 0) {
      setDraftIndex(first)
    }
  }

  return (
    <div className="relative space-y-2">
      <BusyOverlay
        active={busy}
        title="Preparing editable preview"
        message={importStep ?? 'Reading the source, extracting drafts, and checking review signals.'}
      />
      <PageHeader
        eyebrow="Imports"
        title="Preview-first ingestion"
        description={
          <>
            <p>Upload files or paste source reports, review extracted drafts, correct uncertain fields, and only then commit records into the operation.</p>
            {aiStatus ? (
              <p className="mt-2">
                Extraction AI: <span className="font-medium text-foreground">{humanizeToken(aiStatus.provider_mode)}</span>. Gemini is{' '}
                {aiStatus.gemini_enabled && aiStatus.gemini_configured ? 'ready' : 'not ready'}.
              </p>
            ) : null}
            {message ? <p className="mt-2 text-foreground">{message}</p> : null}
            {authError ? <p className="mt-2 text-foreground">Auth error: {authError}</p> : null}
            {previewBlockedReason ? <p className="mt-2">{previewBlockedReason}</p> : null}
          </>
        }
        about="Imports are preview-first: source data is parsed into editable incident, team, and resource drafts. Nothing is stored as operational data until you confirm the reviewed preview."
      />

      <section className="motion-rise motion-delay-1 grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card motion-rise motion-delay-1 p-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-white">Manual source preview</h2>
              <AboutButton>
                Paste a single report, call note, message, or field update here when you do not have a file. The system creates editable drafts from the text before anything is saved.
              </AboutButton>
            </div>
          </div>
          <p className="mt-1 text-sm text-slate-400">Manual text stays here, not in the command center.</p>
          <textarea
            className="mt-4 min-h-32 w-full rounded-xl border border-white/10 bg-black/45 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600"
            placeholder="Flood water rising near Shantinagar bridge. Need rescue boat and medical support..."
            value={manualText}
            onChange={(event) => setManualText(event.target.value)}
          />
          <button
            className="mt-3 w-full rounded-xl border border-foreground bg-foreground px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-background transition hover:bg-foreground/90 disabled:opacity-50 sm:w-auto"
            disabled={busy || !manualText.trim() || Boolean(previewBlockedReason)}
            onClick={() => void startManualPreview()}
          >
            {busy ? <InlineLoading label="Drafting" /> : 'Generate editable preview'}
          </button>
        </div>

        <div className="surface-card motion-rise motion-delay-2 p-4">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-white">Generate preview from file</h2>
            <AboutButton>
              Upload CSV, PDF, or image evidence and choose what kind of records you expect. The preview step lets you inspect, edit, remove, and confirm extracted drafts.
            </AboutButton>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <select className="min-w-0 rounded-xl border border-white/10 bg-black/45 px-3 py-3 text-sm text-white" value={kind} onChange={(event) => {
              setKind(event.target.value as ImportKind)
              setFile(null)
              setFileInputKey((current) => current + 1)
              setCsvText('')
              setCsvPreview(null)
            }}>
              <option value="CSV">CSV</option>
              <option value="PDF">PDF</option>
              <option value="IMAGE">IMAGE</option>
            </select>
            <select className="min-w-0 rounded-xl border border-white/10 bg-black/45 px-3 py-3 text-sm text-white" value={target} onChange={(event) => setTarget(event.target.value as ImportTarget)}>
              <option value="incidents">Incidents</option>
              <option value="teams">Teams</option>
              <option value="resources">Resources</option>
              <option value="mixed">Mixed document</option>
            </select>
            <label className="flex min-w-0 cursor-pointer items-center justify-center rounded-xl border border-dashed border-white/12 bg-white/[0.03] px-3 py-3 text-center text-sm text-slate-300">
              <input
                key={fileInputKey}
                className="hidden"
                type="file"
                accept={kind === 'CSV' ? '.csv' : kind === 'PDF' ? '.pdf' : 'image/*'}
                onChange={(event) => void chooseFile(event.target.files?.[0] ?? null)}
              />
              {file ? file.name : 'Choose import file'}
            </label>
          </div>
          {csvPreview ? <CsvPreviewBlock preview={csvPreview} target={target} csvText={csvText} onChange={updateCsv} /> : null}
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
            <button
              className="w-full rounded-xl border border-foreground bg-foreground px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-background transition hover:bg-foreground/90 disabled:opacity-50 sm:w-auto"
              disabled={!file || busy || Boolean(previewBlockedReason)}
              onClick={() => void submitFilePreview()}
            >
              {busy ? <InlineLoading label="Drafting" /> : 'Generate editable preview'}
            </button>
            <p className="text-sm text-slate-400">{importStep ?? 'Parsing -> drafting -> waiting for confirmation -> commit.'}</p>
          </div>
        </div>
      </section>

      {graphRun ? (
        <Card className="motion-rise motion-delay-2 border-border/80 bg-card/95 shadow-sm">
              <CardHeader className="gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="gap-1">
                  <ClipboardCheck className="size-3" />
                  Review workspace
                </Badge>
                <Badge variant={graphRun.status === 'COMMITTED' ? 'secondary' : 'outline'}>
                  {humanizeToken(graphRun.status)}
                </Badge>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <CardTitle className="text-2xl tracking-[-0.04em] sm:text-3xl">
                  Review {graphRun.drafts.length} editable draft{graphRun.drafts.length === 1 ? '' : 's'}
                </CardTitle>
                <AboutButton>
                  Review workspace is the safety gate before commit. Check warnings, source notes, changed fields, duplicate candidates, and location confidence before storing records.
                </AboutButton>
              </div>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                Confirm clean records, correct uncertain fields, remove noise, and keep every decision explainable before anything is stored.
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap md:justify-end">
              <Button variant="outline" disabled={draftCounts.warnings === 0 || graphRun.drafts.length === 0} onClick={jumpNextUnresolved}>
                Next needs attention
              </Button>
              {graphRun.status === 'COMMITTED' ? (
                <Button variant="outline" onClick={() => void downloadCsv()}>
                  Download CSV
                </Button>
              ) : (
                <Button disabled={busy || graphRun.drafts.filter((draft) => !draft.removed).length === 0} onClick={() => void confirmPreview()}>
                  {busy ? <InlineLoading label="Confirming" /> : 'Confirm all ready drafts'}
                </Button>
              )}
              <Button variant="outline" onClick={() => void clearPreview()}>
                Clear preview
              </Button>
            </div>
          </CardHeader>

          <CardContent className="space-y-5">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <ReviewMetricCard label="Ready to commit" value={draftCounts.ready} note={`${draftCounts.valid} active drafts`} tone="success" />
              <ReviewMetricCard label="Needs attention" value={draftCounts.warnings} note="Warnings, unknown maps, or duplicates" tone={draftCounts.warnings ? 'warning' : 'neutral'} />
              <ReviewMetricCard label="Removed" value={draftCounts.removed} note="Excluded from confirmation" tone="neutral" />
              <ReviewMetricCard label="Committed" value={graphRun.committed_record_ids.length} note="Stored after confirmation" tone="success" />
            </div>

            <div className="rounded-2xl border border-border bg-muted/30 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">Review progress</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {draftCounts.ready + draftCounts.removed} of {graphRun.drafts.length} drafts are either ready or intentionally removed.
                  </p>
                </div>
                <Badge variant="secondary">{draftCounts.reviewProgress}% complete</Badge>
              </div>
              <Progress className="mt-4 h-2" value={draftCounts.reviewProgress} />
            </div>

            {sourceWarnings.length > 0 ? (
              <Alert className="border-foreground/30 bg-foreground/[0.06] text-foreground">
                <AlertTriangle className="size-4" />
                <AlertTitle>Source parsing notes</AlertTitle>
                <AlertDescription>{sourceWarnings.join(' ')}</AlertDescription>
              </Alert>
            ) : null}

            {graphRun.drafts.length === 0 ? (
              <Alert className="border-dashed">
                <FileText className="size-4" />
                <AlertTitle>No reviewable records found</AlertTitle>
                <AlertDescription>
                  No matching data was found for {targetLabels[target]}. Choose a different target, adjust the source text or CSV content, then generate the preview again.
                </AlertDescription>
              </Alert>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-col gap-3 rounded-2xl border border-border bg-background/60 p-3 md:flex-row md:items-center md:justify-between">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Layers3 className="size-4 text-primary" />
                    <span>
                      Showing drafts {draftPageStart} to {draftPageEnd} of {graphRun.drafts.length}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {Array.from({ length: draftPageCount }, (_, pageIndex) => {
                      const start = pageIndex * 10
                      const end = Math.min(start + 10, graphRun.drafts.length)
                      const isActive = draftPage === pageIndex

                      return (
                        <Button
                          key={`draft-page-${pageIndex}`}
                          variant={isActive ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => {
                            setDraftPage(pageIndex)
                            setDraftIndex(start)
                          }}
                          title={`Show previews ${start + 1} to ${end}`}
                        >
                          {pageIndex + 1}
                        </Button>
                      )
                    })}
                  </div>
                </div>

                <div className="grid min-w-0 gap-4 xl:grid-cols-[20rem_minmax(0,1fr)]">
                  <DraftSidebar
                    groups={groupedDrafts.map((group) => ({
                      ...group,
                      drafts: group.drafts.filter((draft) => {
                        const globalIndex = graphRun.drafts.findIndex((item) => item.draft_id === draft.draft_id)
                        return globalIndex >= draftPage * 10 && globalIndex < (draftPage + 1) * 10
                      }),
                    })).filter((group) => group.drafts.length > 0)}
                    activeDraftId={activeDraft?.draft_id ?? null}
                    onSelect={(draftId) => {
                      const index = graphRun.drafts.findIndex((draft) => draft.draft_id === draftId)
                      if (index >= 0) {
                        setDraftIndex(index)
                        setDraftPage(Math.floor(index / 10))
                      }
                    }}
                  />

                  {activeDraft ? (
                    <DraftEditor
                      draft={activeDraft}
                      graphCommitted={graphRun.status === 'COMMITTED'}
                      prompt={editPrompts[activeDraft.draft_id] ?? ''}
                      fieldEdits={fieldEdits[activeDraft.draft_id] ?? {}}
                      reevaluating={reevaluatingDraftId === activeDraft.draft_id}
                      onPromptChange={(value) =>
                        setEditPrompts((current) => ({
                          ...current,
                          [activeDraft.draft_id]: value,
                        }))
                      }
                      onFieldChange={(path, value) =>
                        setFieldEdits((current) => ({
                          ...current,
                          [activeDraft.draft_id]: {
                            ...(current[activeDraft.draft_id] ?? {}),
                            [path]: value,
                          },
                        }))
                      }
                      onEdit={() => void editDraft(activeDraft)}
                      onRemove={() => void removeDraft(activeDraft.draft_id)}
                      onCompareDuplicate={(candidate) =>
                        setDuplicateCompare({ draft: activeDraft, candidate })
                      }
                    />
                  ) : null}
                </div>
              </div>
            )}

            {graphRun.committed_record_ids.length > 0 ? (
              <Alert className="border-foreground/30 bg-foreground/[0.06] text-foreground">
                <CheckCircle2 className="size-4" />
                <AlertTitle>Stored records are ready</AlertTitle>
                <AlertDescription>
                  Use global dispatch planning when you want teams and resources allocated across every open case together.
                </AlertDescription>
                <div className="mt-3 flex flex-wrap gap-2">
                  {committedIncidentIds.length > 0 ? (
                    <Button asChild size="sm">
                      <Link href="/dispatch">Plan all open cases</Link>
                    </Button>
                  ) : null}
                  {graphRun.committed_record_ids.map((id) => (
                    <Button
                      key={id}
                      variant="outline"
                      size="sm"
                      onClick={() => committedIncidentIds.includes(id) ? setPlanningCaseId(id) : undefined}
                    >
                      {id}
                      {committedIncidentIds.includes(id) ? ' | Plan dispatch' : ''}
                    </Button>
                  ))}
                </div>
              </Alert>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {planningCaseId ? <Graph2Panel caseId={planningCaseId} title={`Dispatch plan for ${planningCaseId}`} onCommitted={refreshJobs} /> : null}

      {duplicateCompare ? (
        <DuplicateCompareModal
          draft={duplicateCompare.draft}
          candidate={duplicateCompare.candidate}
          onClose={() => setDuplicateCompare(null)}
          onDiscard={() => {
            void removeDraft(duplicateCompare.draft.draft_id)
            setDuplicateCompare(null)
          }}
        />
      ) : null}

      <SectionCard
        eyebrow="Import jobs"
        title="Processing history"
        description="A searchable log of import preview jobs and cleanup actions for the current organization."
        about="Processing history helps you confirm whether uploads were parsed, committed, removed, or produced warnings. It is scoped to the active organization, so switching organizations changes this list."
        className="motion-rise motion-delay-3"
        action={
          <Input
            className="w-full sm:w-72"
            placeholder="Search jobs..."
            value={jobSearch}
            onChange={(event) => setJobSearch(event.target.value)}
          />
        }
      >
        <div className="grid gap-2 xl:grid-cols-2">
          {jobs.map((job) => (
            <article key={job.job_id} className="rounded-2xl border border-border bg-background/70 p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="truncate font-semibold text-foreground">{job.filename}</h3>
                <Button variant="outline" size="sm" onClick={() => void removeJob(job.job_id)}>
                  Remove
                </Button>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                {humanizeToken(job.kind)} to {humanizeToken(job.target)} | {humanizeToken(job.status)}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">Rows {job.row_count} | Success {job.success_count} | Warnings {job.warning_count}</p>
              {job.error_message ? <p className="mt-3 text-sm text-foreground">{job.error_message}</p> : null}
            </article>
          ))}
          {jobs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border p-6 text-sm text-muted-foreground">No import jobs match this search.</div>
          ) : null}
        </div>
      </SectionCard>
    </div>
  )
}

function ReviewMetricCard({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: number
  note: string
  tone: 'success' | 'warning' | 'neutral'
}) {
  const toneClass =
    tone === 'success'
      ? 'border-foreground/30 bg-foreground/[0.05] text-foreground'
      : tone === 'warning'
        ? 'border-foreground/50 bg-foreground/[0.08] text-foreground'
        : 'border-border bg-background/60 text-foreground'

  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`}>
      <p className="text-xs font-medium uppercase tracking-[0.16em] opacity-70">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.05em]">{value}</p>
      <p className="mt-1 text-sm opacity-75">{note}</p>
    </div>
  )
}

function CsvPreviewBlock({ preview, target, csvText, onChange }: { preview: CsvPreview; target: ImportTarget; csvText: string; onChange: (value: string) => void }) {
  return (
    <div className="mt-4 rounded-2xl border border-white/8 bg-black/35 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">CSV preview and edit step</p>
          <p className="mt-1 text-xs text-slate-500">
            {preview.rowCount} rows detected. Target-aware drafting will only create {targetLabels[target]} drafts from relevant rows.
          </p>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-400">{preview.headers.length} columns</span>
      </div>
      {preview.warnings.length > 0 ? <div className="mt-3 rounded-xl border border-foreground/30 bg-foreground/[0.06] p-3 text-xs text-foreground">{preview.warnings.join(' ')}</div> : null}
      <div className="mt-3 max-h-56 overflow-auto rounded-xl border border-white/8">
        <table className="w-full min-w-[640px] text-left text-xs sm:min-w-[720px]">
          <thead className="bg-white/5 text-slate-400">
            <tr>{preview.headers.map((header) => <th key={header} className="px-3 py-2 font-medium">{header}</th>)}</tr>
          </thead>
          <tbody>
            {preview.rows.map((row, index) => (
              <tr key={`${index}-${JSON.stringify(row)}`} className="border-t border-white/8 text-slate-300">
                {preview.headers.map((header) => <td key={header} className="max-w-64 truncate px-3 py-2">{row[header]}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-sm text-foreground">Edit raw CSV before drafting</summary>
        <textarea className="mt-3 min-h-56 w-full rounded-xl border border-white/10 bg-black/45 px-3 py-2 font-mono text-xs text-white" value={csvText} onChange={(event) => onChange(event.target.value)} />
      </details>
    </div>
  )
}

function DraftSidebar({
  groups,
  activeDraftId,
  onSelect,
}: {
  groups: Array<{ label: string; drafts: RecordDraft[] }>
  activeDraftId: string | null
  onSelect: (draftId: string) => void
}) {
  return (
    <Card className="min-w-0 overflow-hidden border-border/80 bg-background/70" size="sm">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Draft queue</p>
            <CardTitle className="mt-1">Grouped review</CardTitle>
          </div>
          <Badge variant="secondary">{groups.reduce((total, group) => total + group.drafts.length, 0)}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-80 pe-2 xl:h-[42rem]">
          <div className="grid min-w-0 gap-4">
        {groups.map((group) => (
          <div key={group.label} className="min-w-0">
            <div className="flex items-center justify-between text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
              <span className="min-w-0 truncate">{group.label}</span>
              <Badge variant="outline" className="shrink-0">{group.drafts.length}</Badge>
            </div>
            <div className="mt-2 grid min-w-0 gap-2 overflow-hidden">
              {group.drafts.map((draft) => (
                <button
                  key={draft.draft_id}
                  className={`min-w-0 overflow-hidden rounded-xl border px-3 py-2.5 text-left text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    activeDraftId === draft.draft_id
                      ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                      : draft.removed
                        ? 'border-foreground/40 bg-foreground/[0.08] text-foreground opacity-80'
                        : isUnresolved(draft)
                          ? 'border-foreground/50 bg-foreground/[0.08] text-foreground hover:bg-foreground/[0.12]'
                          : 'border-border bg-card text-card-foreground hover:bg-muted'
                  }`}
                  onClick={() => onSelect(draft.draft_id)}
                >
                  <span className="block min-w-0 truncate whitespace-nowrap font-semibold">{draft.title}</span>
                  <span className="mt-1 block min-w-0 truncate whitespace-nowrap text-[11px] opacity-75">
                    {humanizeToken(draft.draft_type)} | {Math.round(draft.confidence * 100)}% confidence | {humanizeToken(draft.map_status ?? 'UNKNOWN')}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}

function DraftEditor({
  draft,
  graphCommitted,
  prompt,
  fieldEdits,
  reevaluating,
  onPromptChange,
  onFieldChange,
  onEdit,
  onRemove,
  onCompareDuplicate,
}: {
  draft: RecordDraft
  graphCommitted: boolean
  prompt: string
  fieldEdits: Record<string, string>
  reevaluating: boolean
  onPromptChange: (value: string) => void
  onFieldChange: (path: string, value: string) => void
  onEdit: () => void
  onRemove: () => void
  onCompareDuplicate: (candidate: DuplicateCandidate) => void
}) {
  const fields = editableFieldsForDraft(draft)
  const duplicateCandidates = ((draft.payload.duplicate_candidates as DuplicateCandidate[] | undefined) ?? [])
  const origin = draftOrigin(draft)
  const sourceHeaders = draft.source_headers ?? ((draft.payload.source_headers as string[] | undefined) ?? [])
  const normalizationTrace = draft.normalization_trace ?? ((draft.payload.normalization_trace as string[] | undefined) ?? [])
  const sourceFragment = draft.source_fragment ?? (typeof draft.payload.source_fragment === 'string' ? draft.payload.source_fragment : '')
  return (
    <Card className={`min-w-0 border-border/80 ${draft.removed ? 'bg-foreground/[0.06] opacity-80' : 'bg-card'}`}>
      <CardHeader className="gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{humanizeToken(draft.draft_type)}</Badge>
            {draft.source_row_index ? <Badge variant="secondary">Row {draft.source_row_index}</Badge> : null}
            <Badge variant={isUnresolved(draft) ? 'destructive' : 'secondary'}>{humanizeToken(draft.map_status ?? 'UNKNOWN')}</Badge>
          </div>
          <CardTitle className="mt-3 break-words text-xl tracking-[-0.03em] sm:text-2xl">{draft.title}</CardTitle>
          <p className="mt-2 text-sm text-muted-foreground">
            Confidence {Math.round(draft.confidence * 100)}% | Provider {humanizeToken(String(draft.payload.provider_used ?? 'Unknown'))}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge className="bg-primary/10 text-primary hover:bg-primary/15" variant="secondary">
              {origin}
            </Badge>
            {draft.geo_resolution_status ?? draft.payload.geo_resolution_status ? (
              <Badge variant="outline">Geo {humanizeToken(String(draft.geo_resolution_status ?? draft.payload.geo_resolution_status))}</Badge>
            ) : null}
            {typeof (draft.adapter_confidence ?? draft.payload.adapter_confidence) === 'number' ? (
              <Badge variant="outline">
                Adapter {Math.round(Number(draft.adapter_confidence ?? draft.payload.adapter_confidence) * 100)}%
              </Badge>
            ) : null}
          </div>
          {draft.changed_fields?.length ? (
            <p className="mt-2 text-sm text-foreground">
              Changed: {draft.changed_fields.map(humanizeToken).join(', ')}
            </p>
          ) : null}
        </div>
        <Button className="w-full sm:w-auto" variant="destructive" disabled={graphCommitted || draft.removed} onClick={onRemove}>
          Remove draft
        </Button>
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="grid gap-3 rounded-2xl border border-border bg-muted/30 p-3 text-sm md:grid-cols-3">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">Source headers</p>
            <p className="mt-1 break-words leading-6 text-foreground/80">{sourceHeaders.length ? sourceHeaders.join(', ') : 'Not a table row'}</p>
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">Normalization trace</p>
            <p className="mt-1 break-words leading-6 text-foreground/80">{normalizationTrace.slice(0, 3).join(' | ') || 'No normalization changes recorded'}</p>
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">Source excerpt</p>
            <p className="mt-1 line-clamp-3 break-words leading-6 text-foreground/80">{sourceFragment || 'Source fragment unavailable'}</p>
          </div>
        </div>

      {draft.warnings.length > 0 ? (
        <div className="grid gap-2">
          {draft.warnings.map((warning) => (
            <Alert key={warning} className="border-foreground/30 bg-foreground/[0.06] text-foreground">
              <AlertTriangle className="size-4" />
              <AlertTitle>Review warning</AlertTitle>
              <AlertDescription>{warning}</AlertDescription>
            </Alert>
          ))}
        </div>
      ) : null}
      {duplicateCandidates.length > 0 ? (
        <div className="rounded-2xl border border-foreground/30 bg-foreground/[0.06] p-3 text-foreground">
          <p className="text-xs font-medium uppercase tracking-[0.18em]">Possible duplicate records</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {duplicateCandidates.map((candidate) => (
              <Button
                key={candidate.record_id}
                variant="outline"
                size="sm"
                onClick={() => onCompareDuplicate(candidate)}
              >
                Compare {candidate.record_id} | {Math.round(candidate.similarity * 100)}%
              </Button>
            ))}
          </div>
        </div>
      ) : null}

        <section className="space-y-3">
          <div>
            <p className="text-sm font-medium text-foreground">Structured fields</p>
            <p className="mt-1 text-sm text-muted-foreground">Edit any field directly, or describe the correction in the prompt below.</p>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {fields.map((field) => (
              <label key={field.path} className="block">
                <span className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">{field.label}</span>
                <Input
                  className="mt-2"
                  disabled={graphCommitted || draft.removed || reevaluating}
                  value={fieldEdits[field.path] ?? field.value}
                  onChange={(event) => onFieldChange(field.path, event.target.value)}
                />
              </label>
            ))}
          </div>
        </section>

        <details className="rounded-2xl border border-border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-medium text-foreground">Show source and extraction details</summary>
          <SourceReviewDetails draft={draft} />
        </details>

        <Separator />

        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" />
            <p className="text-sm font-medium text-foreground">Ask AI to revise this draft</p>
          </div>
          <Textarea
            className="min-h-24"
            placeholder="Example: correct location to Patna City, set latitude 25.5941 and longitude 85.1376, add water rescue requirement..."
            disabled={graphCommitted || draft.removed || reevaluating}
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
          />
          <Button
            className="w-full sm:w-auto"
            disabled={graphCommitted || draft.removed || reevaluating}
            onClick={onEdit}
          >
            {reevaluating ? <InlineLoading label="Reevaluating" /> : 'Reevaluate current draft'}
          </Button>
        </section>
      </CardContent>
    </Card>
  )
}

function DuplicateCompareModal({
  draft,
  candidate,
  onClose,
  onDiscard,
}: {
  draft: RecordDraft
  candidate: DuplicateCandidate
  onClose: () => void
  onDiscard: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4 backdrop-blur">
      <div className="minimal-scrollbar max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-3xl border border-white/15 bg-black p-3 shadow-2xl sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Duplicate compare</p>
            <h3 className="mt-2 break-words text-xl font-semibold tracking-[-0.04em] text-white sm:text-2xl">{draft.title}</h3>
            <p className="mt-2 text-sm text-slate-400">
              Candidate {candidate.record_id} | {Math.round(candidate.similarity * 100)}% | {candidate.suggested_action}
            </p>
          </div>
          <button className="rounded-xl border border-border px-3 py-2 text-xs text-foreground transition hover:bg-muted hover:text-foreground" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-3">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">New draft</p>
            <PrettyFields fields={draft.display_fields || draft.payload} />
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-3">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Existing record evidence</p>
            <div className="mt-2 text-sm leading-6 text-slate-300">
              <p><span className="text-slate-500">Record:</span> {candidate.record_id}</p>
              <p><span className="text-slate-500">Reason:</span> {candidate.reason}</p>
              <p><span className="text-slate-500">Fields:</span> {candidate.fields_compared.join(', ') || 'semantic text'}</p>
              <p><span className="text-slate-500">Geo distance:</span> {candidate.geo_distance_km ?? 'unknown'} km</p>
            </div>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button className="rounded-xl border border-foreground/30 px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-foreground hover:text-background" onClick={onDiscard}>
            Discard new draft
          </button>
          <button className="rounded-xl border border-foreground bg-foreground px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-background transition hover:bg-foreground/90" onClick={onClose}>
            Keep for manual review
          </button>
        </div>
      </div>
    </div>
  )
}

function SourceReviewDetails({ draft }: { draft: RecordDraft }) {
  const payload = draft.payload as Record<string, unknown>
  const sourceFragment = stringValue(payload.source_fragment ?? payload.source_raw_input ?? payload.working_input)
  const sourceHeaders = Array.isArray(payload.source_headers) ? payload.source_headers.map(String).join(', ') : ''
  const rowIndex = stringValue(payload.source_row_index)
  const extractionMode = stringValue(draft.extraction_mode ?? payload.extraction_mode)
  const provider = stringValue(payload.provider_used)
  const confidence = stringValue(payload.adapter_confidence ?? draft.confidence)
  const notes = [
    extractionMode ? `Method: ${humanizeToken(extractionMode)}` : null,
    provider ? `AI/provider: ${humanizeToken(provider)}` : null,
    confidence ? `Confidence: ${confidence}` : null,
    rowIndex ? `Spreadsheet row: ${rowIndex}` : null,
    sourceHeaders ? `Headers: ${sourceHeaders}` : null,
  ].filter((note): note is string => Boolean(note))

  return (
    <div className="mt-3 grid gap-3 rounded-2xl border border-border bg-background/70 p-3 text-sm md:grid-cols-2">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Source report</p>
        <p className="mt-2 line-clamp-5 leading-6 text-muted-foreground">
          {sourceFragment || 'No source excerpt was provided for this draft.'}
        </p>
      </div>
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Extraction notes</p>
        <ul className="mt-2 space-y-1 leading-6 text-muted-foreground">
          {notes.length > 0 ? notes.map((note) => <li key={note}>{note}</li>) : <li>No extra extraction notes were recorded.</li>}
        </ul>
      </div>
    </div>
  )
}

function PrettyFields({ fields }: { fields: Record<string, unknown> }) {
  const entries = Object.entries(fields).filter(([key]) => !['source_row', 'source_raw_input', 'working_input'].includes(key))

  return (
    <dl className="mt-2 grid gap-2 text-sm text-foreground">
      {entries.slice(0, 12).map(([key, value]) => (
        <div key={key} className="rounded-xl border border-border bg-muted/30 p-3">
          <dt className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{humanizeToken(key)}</dt>
          <dd className="mt-1 break-words leading-5 text-foreground/85">{readableValue(value)}</dd>
        </div>
      ))}
      {entries.length === 0 ? <p className="text-sm text-muted-foreground">No display fields were recorded for this draft.</p> : null}
    </dl>
  )
}

function readableValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map(readableValue).join(', ') : 'None listed'
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).slice(0, 5)
    return entries.length > 0
      ? entries.map(([key, nested]) => `${humanizeToken(key)}: ${readableValue(nested)}`).join('; ')
      : 'No details'
  }
  return stringValue(value) || 'Not available'
}

function summarizeDrafts(run: GraphRun | null) {
  const drafts = run?.drafts ?? []
  const valid = drafts.filter((draft) => !draft.removed).length
  const removed = drafts.filter((draft) => draft.removed).length
  const warnings = drafts.filter(isUnresolved).length
  const ready = Math.max(valid - warnings, 0)
  const reviewProgress = drafts.length > 0 ? Math.round(((ready + removed) / drafts.length) * 100) : 0
  return {
    valid,
    removed,
    warnings,
    ready,
    reviewProgress,
  }
}

function groupDrafts(run: GraphRun | null): Array<{ label: string; drafts: RecordDraft[] }> {
  const drafts = run?.drafts ?? []
  const groups = [
    { label: 'Incidents', drafts: drafts.filter((draft) => draft.draft_type === 'INCIDENT') },
    { label: 'Teams', drafts: drafts.filter((draft) => draft.draft_type === 'TEAM') },
    { label: 'Resources', drafts: drafts.filter((draft) => draft.draft_type === 'RESOURCE') },
    { label: 'Needs attention', drafts: drafts.filter(isUnresolved) },
    { label: 'Duplicate warnings', drafts: drafts.filter((draft) => Array.isArray(draft.payload.duplicate_candidates) && draft.payload.duplicate_candidates.length > 0) },
  ]
  return groups.filter((group) => group.drafts.length > 0)
}

function isUnresolved(draft: RecordDraft) {
  return !draft.removed && (draft.warnings.length > 0 || draft.map_status === 'UNKNOWN')
}

function draftOrigin(draft: RecordDraft) {
  const mode = String(draft.extraction_mode ?? draft.payload.extraction_mode ?? '').toLowerCase()
  if (mode.includes('reevaluation')) {
    return 'Reevaluated after operator prompt'
  }
  if (mode === 'csv_fallback_parser') {
    return 'Structured source adapter'
  }
  if (mode.includes('model') || ['gemini', 'ollama'].includes(String(draft.payload.provider_used ?? '').toLowerCase())) {
    return 'Extracted from model'
  }
  if (mode.includes('heuristic') || String(draft.payload.provider_used ?? '').toLowerCase() === 'heuristic') {
    return 'Estimated from source text'
  }
  return 'Extraction source recorded'
}

function editableFieldsForDraft(draft: RecordDraft): Array<{ path: string; label: string; value: string }> {
  if (draft.draft_type === 'TEAM') {
    const team = (draft.payload.team as Record<string, unknown> | undefined) ?? {}
    const baseGeo = (team.base_geo as Record<string, unknown> | null) ?? {}
    const currentGeo = (team.current_geo as Record<string, unknown> | null) ?? {}
    return [
      { path: 'team.team_id', label: 'Team ID', value: stringValue(team.team_id) },
      { path: 'team.display_name', label: 'Team name', value: stringValue(team.display_name) },
      { path: 'team.capability_tags', label: 'Capabilities', value: arrayValue(team.capability_tags) },
      { path: 'team.member_ids', label: 'Member IDs', value: arrayValue(team.member_ids) },
      { path: 'team.base_label', label: 'Base label', value: stringValue(team.base_label) },
      { path: 'team.current_label', label: 'Current label', value: stringValue(team.current_label) },
      { path: 'team.availability_status', label: 'Availability', value: stringValue(team.availability_status) },
      { path: 'team.service_radius_km', label: 'Radius km', value: stringValue(team.service_radius_km) },
      { path: 'team.active_dispatches', label: 'Active dispatches', value: stringValue(team.active_dispatches) },
      { path: 'team.reliability_score', label: 'Reliability', value: stringValue(team.reliability_score) },
      { path: 'team.base_geo.lat', label: 'Base lat', value: stringValue(baseGeo?.lat) },
      { path: 'team.base_geo.lng', label: 'Base lng', value: stringValue(baseGeo?.lng) },
      { path: 'team.current_geo.lat', label: 'Current lat', value: stringValue(currentGeo?.lat) },
      { path: 'team.current_geo.lng', label: 'Current lng', value: stringValue(currentGeo?.lng) },
      { path: 'team.evidence_ids', label: 'Evidence IDs', value: arrayValue(team.evidence_ids) },
      { path: 'team.notes', label: 'Notes', value: arrayValue(team.notes) },
    ]
  }
  if (draft.draft_type === 'RESOURCE') {
    const resource = (draft.payload.resource as Record<string, unknown> | undefined) ?? {}
    const locationGeo = (resource.location as Record<string, unknown> | null) ?? {}
    const currentGeo = (resource.current_geo as Record<string, unknown> | null) ?? {}
    return [
      { path: 'resource.resource_id', label: 'Resource ID', value: stringValue(resource.resource_id) },
      { path: 'resource.resource_type', label: 'Resource type', value: stringValue(resource.resource_type) },
      { path: 'resource.quantity_available', label: 'Quantity', value: stringValue(resource.quantity_available) },
      { path: 'resource.owning_team_id', label: 'Owning team', value: stringValue(resource.owning_team_id) },
      { path: 'resource.location_label', label: 'Location label', value: stringValue(resource.location_label) },
      { path: 'resource.current_label', label: 'Current label', value: stringValue(resource.current_label) },
      { path: 'resource.constraints', label: 'Constraints', value: arrayValue(resource.constraints) },
      { path: 'resource.location.lat', label: 'Location lat', value: stringValue(locationGeo?.lat) },
      { path: 'resource.location.lng', label: 'Location lng', value: stringValue(locationGeo?.lng) },
      { path: 'resource.current_geo.lat', label: 'Current lat', value: stringValue(currentGeo?.lat) },
      { path: 'resource.current_geo.lng', label: 'Current lng', value: stringValue(currentGeo?.lng) },
      { path: 'resource.evidence_ids', label: 'Evidence IDs', value: arrayValue(resource.evidence_ids) },
      { path: 'resource.image_url', label: 'Image URL', value: stringValue(resource.image_url) },
    ]
  }
  const extraction = (draft.payload.extracted as Record<string, unknown> | undefined) ?? {}
  const dataQuality = (extraction.data_quality as Record<string, unknown> | undefined) ?? {}
  const geo = (draft.payload.geo as Record<string, unknown> | null) ?? {}
  return [
    { path: 'extracted.domain', label: 'Domain', value: stringValue(extraction.domain) },
    { path: 'extracted.category', label: 'Category', value: stringValue(extraction.category) },
    { path: 'extracted.subcategory', label: 'Subcategory', value: stringValue(extraction.subcategory) },
    { path: 'extracted.urgency', label: 'Urgency', value: stringValue(extraction.urgency) },
    { path: 'extracted.people_affected', label: 'People affected', value: stringValue(extraction.people_affected) },
    { path: 'extracted.vulnerable_groups', label: 'Vulnerable groups', value: arrayValue(extraction.vulnerable_groups) },
    { path: 'extracted.location_text', label: 'Location text', value: stringValue(extraction.location_text) },
    { path: 'extracted.time_to_act_hours', label: 'Time to act hours', value: stringValue(extraction.time_to_act_hours) },
    { path: 'extracted.required_resources', label: 'Required resources', value: resourceNeedsValue(extraction.required_resources) },
    { path: 'extracted.notes_for_dispatch', label: 'Dispatch notes', value: stringValue(extraction.notes_for_dispatch) },
    { path: 'extracted.confidence', label: 'Extraction confidence', value: stringValue(extraction.confidence) },
    { path: 'extracted.data_quality.missing_location', label: 'Missing location', value: stringValue(dataQuality.missing_location) },
    { path: 'extracted.data_quality.missing_quantity', label: 'Missing quantity', value: stringValue(dataQuality.missing_quantity) },
    { path: 'extracted.data_quality.needs_followup_questions', label: 'Follow-up questions', value: arrayValue(dataQuality.needs_followup_questions) },
    { path: 'location_confidence', label: 'Location confidence', value: stringValue(draft.payload.location_confidence) },
    { path: 'geo.lat', label: 'Lat', value: stringValue(geo?.lat) },
    { path: 'geo.lng', label: 'Lng', value: stringValue(geo?.lng) },
  ]
}

function buildFieldUpdates(draft: RecordDraft, edits: Record<string, string>) {
  const updates: Record<string, unknown> = {}
  const fields = editableFieldsForDraft(draft)
  fields.forEach((field) => {
    if (!(field.path in edits)) {
      return
    }
    const value = edits[field.path]
    if (
      field.path.endsWith('.lat') ||
      field.path.endsWith('.lng') ||
      field.path.endsWith('service_radius_km') ||
      field.path.endsWith('quantity_available') ||
      field.path.endsWith('reliability_score') ||
      field.path.endsWith('people_affected') ||
      field.path.endsWith('time_to_act_hours') ||
      field.path.endsWith('confidence') ||
      field.path.endsWith('active_dispatches')
    ) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) {
        updates[field.path] = parsed
      }
      return
    }
    if (field.path.endsWith('missing_location') || field.path.endsWith('missing_quantity')) {
      updates[field.path] = ['true', 'yes', '1', 'missing'].includes(value.trim().toLowerCase())
      return
    }
    if (
      field.path.endsWith('capability_tags') ||
      field.path.endsWith('constraints') ||
      field.path.endsWith('member_ids') ||
      field.path.endsWith('vulnerable_groups') ||
      field.path.endsWith('evidence_ids') ||
      field.path.endsWith('notes') ||
      field.path.endsWith('needs_followup_questions')
    ) {
      updates[field.path] = parseTags(value)
      return
    }
    updates[field.path] = value
  })
  return updates
}

function stringValue(value: unknown) {
  return value === null || value === undefined ? '' : String(value)
}

function arrayValue(value: unknown) {
  return Array.isArray(value) ? value.map(String).join(', ') : stringValue(value)
}

function resourceNeedsValue(value: unknown) {
  if (!Array.isArray(value)) {
    return stringValue(value)
  }
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') {
        return String(item)
      }
      const record = item as Record<string, unknown>
      const quantity = record.quantity === null || record.quantity === undefined ? '' : `:${record.quantity}`
      const unit = record.unit ? ` ${record.unit}` : ''
      return `${record.resource_type ?? 'RESOURCE'}${quantity}${unit}`
    })
    .join(', ')
}
