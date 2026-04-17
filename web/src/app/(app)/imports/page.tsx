'use client'

import { useEffect, useState } from 'react'

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
import type { AiStatusResponse, GraphRun, IngestionJob } from '@/lib/types'

export default function ImportsPage() {
  const { user } = useAuth()
  const [jobs, setJobs] = useState<IngestionJob[]>([])
  const [kind, setKind] = useState<'CSV' | 'PDF' | 'IMAGE'>('CSV')
  const [target, setTarget] = useState<'incidents' | 'teams' | 'resources'>('incidents')
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [manualText, setManualText] = useState('')
  const [graphRun, setGraphRun] = useState<GraphRun | null>(null)
  const [editPrompts, setEditPrompts] = useState<Record<string, string>>({})
  const [reevaluatingDraftId, setReevaluatingDraftId] = useState<string | null>(null)
  const [csvText, setCsvText] = useState('')
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null)
  const [importStep, setImportStep] = useState<string | null>(null)
  const [aiStatus, setAiStatus] = useState<AiStatusResponse | null>(null)

  useEffect(() => {
    if (!user) {
      return
    }
    void Promise.all([listIngestionJobs(user), getAiStatus(user)]).then(([nextJobs, status]) => {
      setJobs(nextJobs)
      setAiStatus(status)
    })
  }, [user])

  async function submit() {
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
      setMessage(`${file.name} produced ${response.run.drafts.length} editable drafts. Review, edit, remove, then Confirm all.`)
      setFile(null)
      setCsvText('')
      setCsvPreview(null)
      setJobs(await listIngestionJobs(user))
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

  async function startPreview() {
    if (!user || !manualText.trim()) {
      return
    }
    setBusy(true)
    try {
      const response = await runGraph1({ source_kind: 'MANUAL_TEXT', text: manualText, target }, user)
      setGraphRun(response.run)
      setMessage('Graph 1 preview is ready. Confirm, edit with prompt, or remove draft data.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Graph preview failed.')
    } finally {
      setBusy(false)
    }
  }

  async function editDraft(draftId: string) {
    const prompt = editPrompts[draftId]?.trim()
    if (!user || !graphRun || !prompt) {
      return
    }
    setReevaluatingDraftId(draftId)
    try {
      const response = await editGraph1(graphRun.run_id, prompt, draftId, user)
      setGraphRun(response.run)
      setEditPrompts((current) => ({ ...current, [draftId]: '' }))
      setMessage('Draft reevaluated and returned to preview.')
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
      setMessage(`Confirmed graph run ${response.run.run_id}. Records: ${response.run.committed_record_ids.join(', ')}`)
      setJobs(await listIngestionJobs(user))
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

  async function removeCurrentRun() {
    if (!user || !graphRun) {
      return
    }
    const ok = window.confirm('Remove this graph preview/run history? Committed records can be removed from their own pages.')
    if (!ok) {
      return
    }
    await deleteGraphRun(graphRun.run_id, user)
    setGraphRun(null)
    setMessage('Graph run removed.')
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

  return (
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Imports</p>
        <h1 className="mt-2 text-3xl font-semibold">Batch ingestion workspace</h1>
        {aiStatus ? (
          <p className="mt-2 text-sm text-slate-400">
            AI mode: <span className="text-amber-100">{aiStatus.provider_mode}</span> | fallback{' '}
            {aiStatus.fallback_order.join(' -> ')} | Ollama {aiStatus.ollama_model}{' '}
            {aiStatus.ollama_reachable ? 'reachable' : 'not reachable'}
          </p>
        ) : null}
      </header>

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <h2 className="text-lg font-semibold">Graph 1 manual preview</h2>
        <p className="mt-1 text-sm text-slate-400">
          Paste text, preview Docling/Gemini/Ollama drafts, edit with a prompt, remove bad drafts, then confirm to store vectors and records.
        </p>
        <textarea
          className="mt-4 min-h-32 w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-stone-100 outline-none"
          placeholder="Flood water rising near Shantinagar bridge. Need rescue boat and medical support..."
          value={manualText}
          onChange={(event) => setManualText(event.target.value)}
        />
        <button
          className="mt-3 rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={busy || !manualText.trim()}
          onClick={() => void startPreview()}
        >
          {busy ? 'Drafting preview...' : 'Generate editable preview'}
        </button>
      </section>

      {graphRun ? (
        <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Preview run {graphRun.run_id}</h2>
              <p className="mt-1 text-sm text-slate-400">
                {graphRun.status === 'WAITING_FOR_CONFIRMATION'
                  ? 'Waiting for confirmation'
                  : graphRun.status === 'COMMITTED'
                    ? 'Committed'
                    : graphRun.status}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {graphRun.status === 'COMMITTED' ? (
                <button
                  className="rounded-2xl border border-white/10 px-4 py-3 text-sm font-semibold text-slate-200"
                  onClick={() => void downloadCsv()}
                >
                  Download CSV export
                </button>
              ) : null}
              <button
                className="rounded-2xl border border-emerald-300/30 bg-emerald-300/10 px-4 py-3 text-sm font-semibold text-emerald-100 disabled:opacity-50"
                disabled={busy || graphRun.status === 'COMMITTED'}
                onClick={() => void confirmPreview()}
              >
                Confirm all
              </button>
              <button
                className="rounded-2xl border border-white/15 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white hover:text-black"
                onClick={() => void removeCurrentRun()}
              >
                Remove run
              </button>
            </div>
          </div>
          {graphRun.committed_record_ids.length > 0 ? (
            <div className="mt-4 rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-3 text-sm text-emerald-100">
              Stored records:{' '}
              {graphRun.committed_record_ids.map((id, index) => (
                <span key={id}>
                  {index > 0 ? ', ' : ''}
                  {id.startsWith('CASE-') || id.startsWith('DR-') || id.startsWith('HE-') ? (
                    <a className="underline decoration-emerald-200/40 underline-offset-4" href={`/incidents/${id}`}>
                      {id}
                    </a>
                  ) : (
                    id
                  )}
                </span>
              ))}
            </div>
          ) : null}
          <div className="mt-4 grid gap-3">
            {graphRun.drafts.map((draft) => (
              <div key={draft.draft_id} className={`rounded-[1.25rem] border border-white/8 p-4 ${draft.removed ? 'bg-rose-950/20 opacity-60' : 'bg-white/3'}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{draft.draft_type}</p>
                    <h3 className="mt-1 font-semibold text-stone-100">{draft.title}</h3>
                    <p className="mt-2 text-sm text-slate-400">
                      Confidence {Math.round(draft.confidence * 100)}% | Provider{' '}
                      {String(draft.payload.provider_used ?? 'Unknown')}
                    </p>
                    {Array.isArray(draft.payload.provider_fallbacks) && draft.payload.provider_fallbacks.length > 0 ? (
                      <p className="mt-1 text-xs text-slate-500">
                        Fallbacks: {draft.payload.provider_fallbacks.map(String).join(' -> ')}
                      </p>
                    ) : null}
                    {draft.warnings.map((warning) => (
                      <p key={warning} className="mt-2 text-sm text-amber-100">{warning}</p>
                    ))}
                  </div>
                  <button
                    className="rounded-xl border border-rose-400/30 px-3 py-2 text-sm text-rose-200 disabled:opacity-50"
                    disabled={graphRun.status === 'COMMITTED' || draft.removed}
                    onClick={() => void removeDraft(draft.draft_id)}
                  >
                    Remove
                  </button>
                </div>
                <textarea
                  className="mt-3 min-h-20 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-stone-100"
                  placeholder="Prompt edit: correct location to Patna City, add water rescue requirement..."
                  disabled={graphRun.status === 'COMMITTED' || reevaluatingDraftId === draft.draft_id}
                  value={editPrompts[draft.draft_id] ?? ''}
                  onChange={(event) => setEditPrompts((current) => ({ ...current, [draft.draft_id]: event.target.value }))}
                />
                <button
                  className="mt-2 rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
                  disabled={graphRun.status === 'COMMITTED' || reevaluatingDraftId === draft.draft_id || !(editPrompts[draft.draft_id] ?? '').trim()}
                  onClick={() => void editDraft(draft.draft_id)}
                >
                  {reevaluatingDraftId === draft.draft_id ? 'Reevaluating...' : 'Reevaluate this draft'}
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <h2 className="text-lg font-semibold">Generate preview from file</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <select
            className="rounded-2xl border border-white/10 bg-slate-950/70 px-3 py-3 text-sm text-stone-100"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as 'CSV' | 'PDF' | 'IMAGE')
              setFile(null)
              setCsvText('')
              setCsvPreview(null)
            }}
          >
            <option value="CSV">CSV</option>
            <option value="PDF">PDF</option>
            <option value="IMAGE">IMAGE</option>
          </select>
          <select
            className="rounded-2xl border border-white/10 bg-slate-950/70 px-3 py-3 text-sm text-stone-100"
            value={target}
            onChange={(event) => setTarget(event.target.value as 'incidents' | 'teams' | 'resources')}
          >
            <option value="incidents">Incidents</option>
            <option value="teams">Teams</option>
            <option value="resources">Resources</option>
          </select>
          <label className="flex cursor-pointer items-center justify-center rounded-2xl border border-dashed border-white/12 bg-white/3 px-3 py-3 text-sm text-slate-300">
            <input
              className="hidden"
              type="file"
              accept={kind === 'CSV' ? '.csv' : kind === 'PDF' ? '.pdf' : 'image/*'}
              onChange={(event) => void chooseFile(event.target.files?.[0] ?? null)}
            />
            {file ? file.name : 'Choose import file'}
          </label>
        </div>
        {csvPreview ? (
          <div className="mt-4 rounded-2xl border border-white/8 bg-slate-950/55 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-stone-100">CSV preview and edit step</p>
                <p className="mt-1 text-xs text-slate-500">
                  {csvPreview.rowCount} rows detected for {target}. Nothing is stored until you generate the preview and confirm it.
                </p>
              </div>
              <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-400">
                {csvPreview.headers.length} columns
              </span>
            </div>
            {csvPreview.warnings.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-300/20 bg-amber-300/10 p-3 text-xs text-amber-100">
                {csvPreview.warnings.join(' ')}
              </div>
            ) : null}
            <div className="mt-3 max-h-56 overflow-auto rounded-xl border border-white/8">
              <table className="w-full min-w-[720px] text-left text-xs">
                <thead className="bg-white/5 text-slate-400">
                  <tr>
                    {csvPreview.headers.map((header) => (
                      <th key={header} className="px-3 py-2 font-medium">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {csvPreview.rows.map((row, index) => (
                    <tr key={`${index}-${JSON.stringify(row)}`} className="border-t border-white/8 text-slate-300">
                      {csvPreview.headers.map((header) => (
                        <td key={header} className="max-w-64 truncate px-3 py-2">
                          {row[header]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details className="mt-3">
              <summary className="cursor-pointer text-sm text-amber-100">Edit raw CSV before drafting</summary>
              <textarea
                className="mt-3 min-h-56 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 font-mono text-xs text-stone-100"
                value={csvText}
                onChange={(event) => updateCsv(event.target.value)}
              />
            </details>
          </div>
        ) : null}
        <div className="mt-4 flex items-center gap-3">
          <button
            className="rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!file || busy}
            onClick={() => void submit()}
          >
            {busy ? 'Drafting...' : 'Generate editable preview'}
          </button>
          <p className="text-sm text-slate-400">
            {importStep ?? message ?? 'Parsing -> Drafting with provider -> Waiting for confirmation -> Commit.'}
          </p>
        </div>
      </section>

      <section className="grid gap-3 xl:grid-cols-2">
        {jobs.map((job) => (
          <div key={job.job_id} className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-stone-100">{job.filename}</h2>
              <div className="flex items-center gap-2">
                <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                  {job.status}
                </span>
                <button
                  className="rounded-full border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black"
                  onClick={() => void removeJob(job.job_id)}
                >
                  Remove
                </button>
              </div>
            </div>
            <p className="mt-2 text-sm text-slate-400">
              {job.kind} {'->'} {job.target}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Rows {job.row_count} | Success {job.success_count} | Warnings {job.warning_count}
            </p>
            {job.error_message ? <p className="mt-3 text-sm text-rose-200">{job.error_message}</p> : null}
          </div>
        ))}
        {jobs.length === 0 ? (
          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5 text-sm text-slate-500">
            Start an import to see processing history here.
          </div>
        ) : null}
      </section>
    </div>
  )
}
