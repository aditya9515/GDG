'use client'

import { useEffect, useMemo, useState } from 'react'

import { Graph2Panel } from '@/components/dispatch/graph2-panel'
import { useAuth } from '@/components/providers/auth-provider'
import {
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
import { parseTags } from '@/lib/form-utils'
import type { AiStatusResponse, GraphRun, IngestionJob, RecordDraft } from '@/lib/types'

type ImportKind = 'CSV' | 'PDF' | 'IMAGE'
type ImportTarget = 'incidents' | 'teams' | 'resources'

const targetLabels: Record<ImportTarget, string> = {
  incidents: 'Incidents',
  teams: 'Teams',
  resources: 'Resources',
}

export default function ImportsPage() {
  const { user } = useAuth()
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
  const [editPrompts, setEditPrompts] = useState<Record<string, string>>({})
  const [fieldEdits, setFieldEdits] = useState<Record<string, Record<string, string>>>({})
  const [reevaluatingDraftId, setReevaluatingDraftId] = useState<string | null>(null)
  const [csvText, setCsvText] = useState('')
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null)
  const [importStep, setImportStep] = useState<string | null>(null)
  const [aiStatus, setAiStatus] = useState<AiStatusResponse | null>(null)
  const [jobSearch, setJobSearch] = useState('')
  const [planningCaseId, setPlanningCaseId] = useState<string | null>(null)

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
      return
    }
    setDraftIndex((current) => Math.min(current, Math.max(graphRun.drafts.length - 1, 0)))
  }, [graphRun])

  const activeDraft = graphRun?.drafts[draftIndex] ?? null
  const draftCounts = useMemo(() => summarizeDrafts(graphRun), [graphRun])
  const committedIncidentIds = useMemo(
    () => graphRun?.committed_record_ids.filter((id) => id.startsWith('CASE-') || id.startsWith('DR-') || id.startsWith('HE-')) ?? [],
    [graphRun],
  )

  async function refreshJobs() {
    if (!user) {
      return
    }
    setJobs(await listIngestionJobs(user, jobSearch))
  }

  async function submitFilePreview() {
    if (!user || !file) {
      return
    }
    setBusy(true)
    setMessage(null)
    setImportStep(`Parsing ${file.name}...`)
    try {
      const uploadFile = kind === 'CSV' && csvText.trim() ? csvTextToFile(csvText, file.name) : file
      const response = await runGraph1File({ kind, target, file: uploadFile }, user, { onProgress: setImportStep })
      setGraphRun(response.run)
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
    if (!user || !manualText.trim()) {
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const response = await runGraph1({ source_kind: 'MANUAL_TEXT', text: manualText, target }, user)
      setGraphRun(response.run)
      setDraftIndex(0)
      setMessage('Graph 1 preview is ready. Confirm, edit with prompt, or remove draft data.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Graph preview failed.')
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
      setMessage(`Confirmed graph run ${response.run.run_id}. Records: ${response.run.committed_record_ids.join(', ') || 'none'}`)
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
    <div className="space-y-2">
      <header className="border border-white/14 bg-black/35 p-4">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Imports</p>
        <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] text-white">Preview-first ingestion</h1>
        {aiStatus ? (
          <p className="mt-2 text-sm text-slate-400">
            AI mode: <span className="text-amber-100">{aiStatus.provider_mode}</span> | fallback{' '}
            {aiStatus.fallback_order.join(' -> ')} | Ollama {aiStatus.ollama_model}{' '}
            {aiStatus.ollama_reachable ? 'reachable' : 'not reachable'}
          </p>
        ) : null}
        {message ? <p className="mt-2 text-sm text-amber-100">{message}</p> : null}
      </header>

      <section className="grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card p-4">
          <h2 className="text-lg font-semibold text-white">Manual Graph 1 preview</h2>
          <p className="mt-1 text-sm text-slate-400">Manual text stays here, not in the command center.</p>
          <textarea
            className="mt-4 min-h-32 w-full border border-white/10 bg-black/45 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600"
            placeholder="Flood water rising near Shantinagar bridge. Need rescue boat and medical support..."
            value={manualText}
            onChange={(event) => setManualText(event.target.value)}
          />
          <button
            className="mt-3 border border-white/15 bg-white px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:opacity-50"
            disabled={busy || !manualText.trim()}
            onClick={() => void startManualPreview()}
          >
            {busy ? 'Drafting...' : 'Generate editable preview'}
          </button>
        </div>

        <div className="surface-card p-4">
          <h2 className="text-lg font-semibold text-white">Generate preview from file</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <select className="border border-white/10 bg-black/45 px-3 py-3 text-sm text-white" value={kind} onChange={(event) => {
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
            <select className="border border-white/10 bg-black/45 px-3 py-3 text-sm text-white" value={target} onChange={(event) => setTarget(event.target.value as ImportTarget)}>
              <option value="incidents">Incidents</option>
              <option value="teams">Teams</option>
              <option value="resources">Resources</option>
            </select>
            <label className="flex cursor-pointer items-center justify-center border border-dashed border-white/12 bg-white/[0.03] px-3 py-3 text-sm text-slate-300">
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
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              className="border border-white/15 bg-white px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:opacity-50"
              disabled={!file || busy}
              onClick={() => void submitFilePreview()}
            >
              {busy ? 'Drafting...' : 'Generate editable preview'}
            </button>
            <p className="text-sm text-slate-400">{importStep ?? 'Parsing -> drafting -> waiting for confirmation -> commit.'}</p>
          </div>
        </div>
      </section>

      {graphRun ? (
        <section className="border border-white/10 bg-black/35 p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Preview run</p>
              <h2 className="mt-2 text-xl font-semibold text-white">{graphRun.run_id}</h2>
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                <span className="border border-white/10 px-2 py-1">{graphRun.status}</span>
                <span className="border border-white/10 px-2 py-1">{draftCounts.valid} valid</span>
                <span className="border border-white/10 px-2 py-1">{draftCounts.removed} removed</span>
                <span className="border border-white/10 px-2 py-1">{draftCounts.warnings} warnings</span>
                <span className="border border-white/10 px-2 py-1">{graphRun.committed_record_ids.length} committed</span>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="border border-white/15 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black" onClick={jumpNextUnresolved}>
                Next unresolved
              </button>
              {graphRun.status === 'COMMITTED' ? (
                <button className="border border-white/15 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black" onClick={() => void downloadCsv()}>
                  Download CSV
                </button>
              ) : (
                <button
                  className="border border-emerald-300/30 bg-emerald-300/10 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-emerald-100 disabled:opacity-50"
                  disabled={busy || graphRun.drafts.filter((draft) => !draft.removed).length === 0}
                  onClick={() => void confirmPreview()}
                >
                  Confirm all
                </button>
              )}
              <button className="border border-white/15 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black" onClick={() => void clearPreview()}>
                Clear preview
              </button>
            </div>
          </div>

          {graphRun.source_artifacts.flatMap((artifact) => artifact.parse_warnings).length > 0 ? (
            <div className="mt-4 border border-amber-300/25 bg-amber-300/10 p-3 text-sm text-amber-100">
              {graphRun.source_artifacts.flatMap((artifact) => artifact.parse_warnings).join(' ')}
            </div>
          ) : null}

          {graphRun.drafts.length === 0 ? (
            <div className="mt-4 border border-dashed border-white/10 p-6 text-sm text-slate-500">
              No matching data found for {targetLabels[target]}. Choose the correct target or edit the CSV headers and generate preview again.
            </div>
          ) : (
            <div className="mt-4">
              <div className="flex flex-wrap gap-1.5">
                {graphRun.drafts.map((draft, index) => (
                  <button
                    key={draft.draft_id}
                    className={`border px-3 py-2 text-xs font-semibold transition ${
                      draftIndex === index
                        ? 'border-white bg-white text-black'
                        : isUnresolved(draft)
                          ? 'border-amber-300/40 text-amber-100 hover:bg-white hover:text-black'
                          : 'border-white/10 text-slate-400 hover:bg-white hover:text-black'
                    }`}
                    onClick={() => setDraftIndex(index)}
                  >
                    {index + 1}
                  </button>
                ))}
              </div>
              {activeDraft ? (
                <DraftEditor
                  draft={activeDraft}
                  graphCommitted={graphRun.status === 'COMMITTED'}
                  prompt={editPrompts[activeDraft.draft_id] ?? ''}
                  fieldEdits={fieldEdits[activeDraft.draft_id] ?? {}}
                  reevaluating={reevaluatingDraftId === activeDraft.draft_id}
                  onPromptChange={(value) => setEditPrompts((current) => ({ ...current, [activeDraft.draft_id]: value }))}
                  onFieldChange={(path, value) =>
                    setFieldEdits((current) => ({
                      ...current,
                      [activeDraft.draft_id]: { ...(current[activeDraft.draft_id] ?? {}), [path]: value },
                    }))
                  }
                  onEdit={() => void editDraft(activeDraft)}
                  onRemove={() => void removeDraft(activeDraft.draft_id)}
                />
              ) : null}
            </div>
          )}

          {graphRun.committed_record_ids.length > 0 ? (
            <div className="mt-4 border border-emerald-300/20 bg-emerald-300/10 p-3 text-sm text-emerald-100">
              <p className="font-semibold">Stored records</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {graphRun.committed_record_ids.map((id) => (
                  <button
                    key={id}
                    className="border border-emerald-200/30 px-2 py-1 text-xs text-emerald-50 transition hover:bg-white hover:text-black"
                    onClick={() => committedIncidentIds.includes(id) ? setPlanningCaseId(id) : undefined}
                  >
                    {id}
                    {committedIncidentIds.includes(id) ? ' | Plan dispatch' : ''}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {planningCaseId ? <Graph2Panel caseId={planningCaseId} title={`Dispatch plan for ${planningCaseId}`} onCommitted={refreshJobs} /> : null}

      <section className="border border-white/10 bg-black/35 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Import jobs</p>
            <h2 className="mt-2 text-xl font-semibold text-white">Processing history</h2>
          </div>
          <input
            className="border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Search jobs..."
            value={jobSearch}
            onChange={(event) => setJobSearch(event.target.value)}
          />
        </div>
        <div className="mt-4 grid gap-2 xl:grid-cols-2">
          {jobs.map((job) => (
            <article key={job.job_id} className="border border-white/10 bg-white/[0.025] p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="truncate font-semibold text-white">{job.filename}</h3>
                <button className="border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black" onClick={() => void removeJob(job.job_id)}>
                  Remove
                </button>
              </div>
              <p className="mt-2 text-sm text-slate-400">{job.kind} -&gt; {job.target} | {job.status}</p>
              <p className="mt-2 text-xs text-slate-500">Rows {job.row_count} | Success {job.success_count} | Warnings {job.warning_count}</p>
              {job.error_message ? <p className="mt-3 text-sm text-rose-200">{job.error_message}</p> : null}
            </article>
          ))}
          {jobs.length === 0 ? (
            <div className="border border-dashed border-white/10 p-6 text-sm text-slate-500">No import jobs match this search.</div>
          ) : null}
        </div>
      </section>
    </div>
  )
}

function CsvPreviewBlock({ preview, target, csvText, onChange }: { preview: CsvPreview; target: ImportTarget; csvText: string; onChange: (value: string) => void }) {
  return (
    <div className="mt-4 border border-white/8 bg-black/35 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">CSV preview and edit step</p>
          <p className="mt-1 text-xs text-slate-500">
            {preview.rowCount} rows detected. Target-aware drafting will only create {targetLabels[target]} drafts from relevant rows.
          </p>
        </div>
        <span className="border border-white/10 px-3 py-1 text-xs text-slate-400">{preview.headers.length} columns</span>
      </div>
      {preview.warnings.length > 0 ? <div className="mt-3 border border-amber-300/20 bg-amber-300/10 p-3 text-xs text-amber-100">{preview.warnings.join(' ')}</div> : null}
      <div className="mt-3 max-h-56 overflow-auto border border-white/8">
        <table className="w-full min-w-[720px] text-left text-xs">
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
        <summary className="cursor-pointer text-sm text-amber-100">Edit raw CSV before drafting</summary>
        <textarea className="mt-3 min-h-56 w-full border border-white/10 bg-black/45 px-3 py-2 font-mono text-xs text-white" value={csvText} onChange={(event) => onChange(event.target.value)} />
      </details>
    </div>
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
}) {
  const fields = editableFieldsForDraft(draft)
  return (
    <article className={`mt-4 border border-white/10 p-4 ${draft.removed ? 'bg-rose-950/20 opacity-70' : 'bg-white/[0.025]'}`}>
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
            {draft.draft_type} {draft.source_row_index ? `| row ${draft.source_row_index}` : ''} | {draft.map_status ?? 'UNKNOWN'}
          </p>
          <h3 className="mt-1 text-lg font-semibold text-white">{draft.title}</h3>
          <p className="mt-2 text-sm text-slate-400">
            Confidence {Math.round(draft.confidence * 100)}% | Provider {String(draft.payload.provider_used ?? 'Unknown')}
          </p>
          {draft.changed_fields?.length ? <p className="mt-2 text-xs text-emerald-100">Changed: {draft.changed_fields.join(', ')}</p> : null}
        </div>
        <button className="border border-rose-400/30 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-rose-100 disabled:opacity-50" disabled={graphCommitted || draft.removed} onClick={onRemove}>
          Remove draft
        </button>
      </div>
      {draft.warnings.length > 0 ? (
        <div className="mt-3 grid gap-2">
          {draft.warnings.map((warning) => <p key={warning} className="border border-amber-300/20 bg-amber-300/10 p-2 text-sm text-amber-100">{warning}</p>)}
        </div>
      ) : null}
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {fields.map((field) => (
          <label key={field.path} className="block">
            <span className="text-xs uppercase tracking-[0.16em] text-slate-500">{field.label}</span>
            <input
              className="mt-2 w-full border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25 disabled:opacity-60"
              disabled={graphCommitted || draft.removed || reevaluating}
              value={fieldEdits[field.path] ?? field.value}
              onChange={(event) => onFieldChange(field.path, event.target.value)}
            />
          </label>
        ))}
      </div>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm text-slate-300">Show generated payload and source row</summary>
        <pre className="mt-3 max-h-72 overflow-auto border border-white/10 bg-black/55 p-3 text-xs leading-5 text-slate-300">
          {JSON.stringify({ display_fields: draft.display_fields, source_row: draft.payload.source_row, payload: draft.payload }, null, 2)}
        </pre>
      </details>
      <textarea
        className="mt-4 min-h-20 w-full border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600"
        placeholder="Prompt edit: correct location to Patna City, add water rescue requirement..."
        disabled={graphCommitted || draft.removed || reevaluating}
        value={prompt}
        onChange={(event) => onPromptChange(event.target.value)}
      />
      <button
        className="mt-3 border border-white/15 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:opacity-50"
        disabled={graphCommitted || draft.removed || reevaluating}
        onClick={onEdit}
      >
        {reevaluating ? 'Reevaluating...' : 'Reevaluate current draft'}
      </button>
    </article>
  )
}

function summarizeDrafts(run: GraphRun | null) {
  const drafts = run?.drafts ?? []
  return {
    valid: drafts.filter((draft) => !draft.removed).length,
    removed: drafts.filter((draft) => draft.removed).length,
    warnings: drafts.filter(isUnresolved).length,
  }
}

function isUnresolved(draft: RecordDraft) {
  return !draft.removed && (draft.warnings.length > 0 || draft.map_status === 'UNKNOWN')
}

function editableFieldsForDraft(draft: RecordDraft): Array<{ path: string; label: string; value: string }> {
  if (draft.draft_type === 'TEAM') {
    const team = (draft.payload.team as Record<string, unknown> | undefined) ?? {}
    const geo = (team.base_geo as Record<string, unknown> | null) ?? {}
    return [
      { path: 'team.display_name', label: 'Team name', value: stringValue(team.display_name) },
      { path: 'team.capability_tags', label: 'Capabilities', value: arrayValue(team.capability_tags) },
      { path: 'team.base_label', label: 'Base label', value: stringValue(team.base_label) },
      { path: 'team.service_radius_km', label: 'Radius km', value: stringValue(team.service_radius_km) },
      { path: 'team.base_geo.lat', label: 'Base lat', value: stringValue(geo?.lat) },
      { path: 'team.base_geo.lng', label: 'Base lng', value: stringValue(geo?.lng) },
    ]
  }
  if (draft.draft_type === 'RESOURCE') {
    const resource = (draft.payload.resource as Record<string, unknown> | undefined) ?? {}
    const geo = (resource.location as Record<string, unknown> | null) ?? {}
    return [
      { path: 'resource.resource_type', label: 'Resource type', value: stringValue(resource.resource_type) },
      { path: 'resource.quantity_available', label: 'Quantity', value: stringValue(resource.quantity_available) },
      { path: 'resource.location_label', label: 'Location label', value: stringValue(resource.location_label) },
      { path: 'resource.constraints', label: 'Constraints', value: arrayValue(resource.constraints) },
      { path: 'resource.location.lat', label: 'Location lat', value: stringValue(geo?.lat) },
      { path: 'resource.location.lng', label: 'Location lng', value: stringValue(geo?.lng) },
    ]
  }
  const extraction = (draft.payload.extracted as Record<string, unknown> | undefined) ?? {}
  const geo = (draft.payload.geo as Record<string, unknown> | null) ?? {}
  return [
    { path: 'extracted.category', label: 'Category', value: stringValue(extraction.category) },
    { path: 'extracted.urgency', label: 'Urgency', value: stringValue(extraction.urgency) },
    { path: 'extracted.location_text', label: 'Location text', value: stringValue(extraction.location_text) },
    { path: 'extracted.notes_for_dispatch', label: 'Dispatch notes', value: stringValue(extraction.notes_for_dispatch) },
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
    if (field.path.endsWith('.lat') || field.path.endsWith('.lng') || field.path.endsWith('service_radius_km') || field.path.endsWith('quantity_available')) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) {
        updates[field.path] = parsed
      }
      return
    }
    if (field.path.endsWith('capability_tags') || field.path.endsWith('constraints')) {
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

