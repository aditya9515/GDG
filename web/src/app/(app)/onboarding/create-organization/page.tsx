'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { createOrganization } from '@/lib/api'

export default function CreateOrganizationPage() {
  const router = useRouter()
  const { user, setActiveOrg, refreshSession } = useAuth()
  const [name, setName] = useState('ReliefOps Demo NGO')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!user || !name.trim()) {
      return
    }
    setBusy(true)
    setMessage('Creating organization and assigning host access...')
    try {
      const response = await createOrganization(name, user)
      setActiveOrg(response.organization.org_id)
      await refreshSession()
      setActiveOrg(response.organization.org_id)
      setMessage('Organization created. Opening command center. You can invite Gmail users from Organization.')
      router.replace('/command-center')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create organization.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Host onboarding</p>
        <h1 className="mt-2 text-3xl font-semibold">Create your NGO organization</h1>
        <p className="mt-2 text-sm leading-6 text-slate-400">
          The creator becomes the host. Hosts can invite Gmail users, view members, change roles, and remove access.
        </p>
      </header>

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <label className="text-sm font-medium text-stone-100">
          Organization name
          <input
            className="mt-3 w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-stone-100 outline-none"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button
          className="mt-4 rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={busy || !name.trim()}
          onClick={() => void submit()}
        >
          {busy ? 'Creating...' : 'Create organization'}
        </button>
        {message ? <p className="mt-4 text-sm text-slate-300">{message}</p> : null}
      </section>
    </div>
  )
}
