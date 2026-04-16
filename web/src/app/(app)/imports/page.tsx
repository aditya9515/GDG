'use client'

import { useEffect, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { confirmGraph1, createIngestionJob, editGraph1, listIngestionJobs, removeGraph1Draft, runGraph1 } from '@/lib/api'
import { csvTextToFile, parseCsvPreview, type CsvPreview } from '@/lib/csv-preview'
import type { GraphRun, IngestionJob } from '@/lib/types'

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
  const [editPrompt, setEditPrompt] = useState('')
  const [csvText, setCsvText] = useState('')
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null)
  const [importStep, setImportStep] = useState<string | null>(null)

  useEffect(() => {
    if (!user) {
      return
    }
    void listIngestionJobs(user).then(setJobs)
  }, [user])

  async function submit() {
    if (!user || !file) {
      return
    }
    setBusy(true)
    setMessage(null)
    setImportStep(`Preparing ${file.name}...`)
    try {
      const uploadFile = kind === 'CSV' && csvText.trim() ? csvTextToFile(csvText, file.name) : file
      const job = await createIngestionJob({ kind, target, file: uploadFile }, user, { onProgress: setImportStep })
      setMessage(`${file.name} imported successfully. ${job.success_count} records created from ${job.row_count || 'the'} rows.`)
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
    if (!user || !graphRun || !editPrompt.trim()) {
      return
    }
    setBusy(true)
    try {
      const response = await editGraph1(graphRun.run_id, editPrompt, draftId, user)
      setGraphRun(response.run)
      setEditPrompt('')
    } finally {
      setBusy(false)
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
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Imports</p>
        <h1 className="mt-2 text-3xl font-semibold">Batch ingestion workspace</h1>
      </header>

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <h2 className="text-lg font-semibold">Graph 1 manual preview</h2>
        <p className="mt-1 text-sm text-slate-400">
          Paste text, preview Docling/Gemini drafts, edit with a prompt, remove bad drafts, then confirm to store vectors and records.
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
          {busy ? 'Running graph...' : 'Run Graph 1 preview'}
        </button>
      </section>

      {graphRun ? (
        <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Preview run {graphRun.run_id}</h2>
              <p className="mt-1 text-sm text-slate-400">{graphRun.status}</p>
            </div>
            <button
              className="rounded-2xl border border-emerald-300/30 bg-emerald-300/10 px-4 py-3 text-sm font-semibold text-emerald-100 disabled:opacity-50"
              disabled={busy || graphRun.status === 'COMMITTED'}
              onClick={() => void confirmPreview()}
            >
              Confirm all
            </button>
          </div>
          <div className="mt-4 grid gap-3">
            {graphRun.drafts.map((draft) => (
              <div key={draft.draft_id} className={`rounded-[1.25rem] border border-white/8 p-4 ${draft.removed ? 'bg-rose-950/20 opacity-60' : 'bg-white/3'}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{draft.draft_type}</p>
                    <h3 className="mt-1 font-semibold text-stone-100">{draft.title}</h3>
                    <p className="mt-2 text-sm text-slate-400">Confidence {Math.round(draft.confidence * 100)}%</p>
                    {draft.warnings.map((warning) => (
                      <p key={warning} className="mt-2 text-sm text-amber-100">{warning}</p>
                    ))}
                  </div>
                  <button className="rounded-xl border border-rose-400/30 px-3 py-2 text-sm text-rose-200" onClick={() => void removeDraft(draft.draft_id)}>
                    Remove
                  </button>
                </div>
                <textarea
                  className="mt-3 min-h-20 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-stone-100"
                  placeholder="Prompt edit: correct location to Patna City, add water rescue requirement..."
                  value={editPrompt}
                  onChange={(event) => setEditPrompt(event.target.value)}
                />
                <button
                  className="mt-2 rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
                  disabled={busy || !editPrompt.trim()}
                  onClick={() => void editDraft(draft.draft_id)}
                >
                  Reevaluate this draft
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <h2 className="text-lg font-semibold">Start new ingestion job</h2>
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
                  {csvPreview.rowCount} rows detected for {target}. Nothing is stored until you press Start import.
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
              <summary className="cursor-pointer text-sm text-amber-100">Edit raw CSV before committing</summary>
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
            {busy ? 'Importing...' : kind === 'CSV' ? 'Start import after preview' : 'Start import'}
          </button>
          <p className="text-sm text-slate-400">
            {importStep ?? message ?? 'CSV imports create records. PDF and image imports create evidence-backed incidents.'}
          </p>
        </div>
      </section>

      <section className="grid gap-3 xl:grid-cols-2">
        {jobs.map((job) => (
          <div key={job.job_id} className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-stone-100">{job.filename}</h2>
              <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                {job.status}
              </span>
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
