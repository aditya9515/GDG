'use client'

import { useEffect, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { createIngestionJob, listIngestionJobs } from '@/lib/api'
import type { IngestionJob } from '@/lib/types'

export default function ImportsPage() {
  const { user } = useAuth()
  const [jobs, setJobs] = useState<IngestionJob[]>([])
  const [kind, setKind] = useState<'CSV' | 'PDF' | 'IMAGE'>('CSV')
  const [target, setTarget] = useState<'incidents' | 'teams' | 'resources'>('incidents')
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
    try {
      await createIngestionJob({ kind, target, file }, user)
      setMessage(`${file.name} imported successfully.`)
      setFile(null)
      setJobs(await listIngestionJobs(user))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Import failed.')
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
        <h2 className="text-lg font-semibold">Start new ingestion job</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <select
            className="rounded-2xl border border-white/10 bg-slate-950/70 px-3 py-3 text-sm text-stone-100"
            value={kind}
            onChange={(event) => setKind(event.target.value as 'CSV' | 'PDF' | 'IMAGE')}
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
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            {file ? file.name : 'Choose import file'}
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            className="rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!file || busy}
            onClick={() => void submit()}
          >
            {busy ? 'Importing...' : 'Start import'}
          </button>
          <p className="text-sm text-slate-400">{message ?? 'CSV imports create records. PDF and image imports create evidence-backed incidents.'}</p>
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
              Rows {job.row_count} • Success {job.success_count} • Warnings {job.warning_count}
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
