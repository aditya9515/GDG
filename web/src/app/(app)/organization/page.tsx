'use client'

import { useEffect, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import {
  createOrganization,
  getOrganizationMembers,
  inviteOrgMember,
  removeOrgMember,
  resetOrganizationData,
  updateOrgMember,
} from '@/lib/api'
import type { OrgInvite, OrgMembership, OrgRole, Organization } from '@/lib/types'

const roles: OrgRole[] = ['INCIDENT_COORDINATOR', 'MEDICAL_COORDINATOR', 'LOGISTICS_LEAD', 'VIEWER']

export default function OrganizationPage() {
  const { user, setActiveOrg, refreshSession } = useAuth()
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [members, setMembers] = useState<OrgMembership[]>([])
  const [invites, setInvites] = useState<OrgInvite[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<OrgRole>('VIEWER')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newOrgName, setNewOrgName] = useState('')
  const [resetConfirm, setResetConfirm] = useState('')
  const [resetBusy, setResetBusy] = useState(false)
  const [resetSummary, setResetSummary] = useState<string | null>(null)

  useEffect(() => {
    if (!user?.active_org_id || !user.is_host) {
      return
    }
    void refresh()
  }, [user?.active_org_id, user?.is_host])

  async function refresh() {
    if (!user?.active_org_id) {
      return
    }
    const payload = await getOrganizationMembers(user.active_org_id, user)
    setOrganization(payload.organization)
    setMembers(payload.members)
    setInvites(payload.invites)
  }

  async function invite() {
    if (!user?.active_org_id || !email.trim()) {
      return
    }
    setBusy(true)
    try {
      await inviteOrgMember(user.active_org_id, email, role, user)
      setEmail('')
      setMessage(`Invited ${email}. They can sign in with Google using that Gmail.`)
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Invite failed.')
    } finally {
      setBusy(false)
    }
  }

  async function createAnotherOrganization() {
    if (!user || !newOrgName.trim()) {
      return
    }
    setBusy(true)
    try {
      const response = await createOrganization(newOrgName, user)
      await refreshSession()
      setActiveOrg(response.organization.org_id)
      setNewOrgName('')
      setMessage(`Created ${response.organization.name}. You are the host of this organization.`)
      setOrganization(response.organization)
      setMembers([response.membership])
      setInvites([])
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create organization.')
    } finally {
      setBusy(false)
    }
  }

  async function changeRole(member: OrgMembership, nextRole: OrgRole) {
    if (!user?.active_org_id) {
      return
    }
    await updateOrgMember(user.active_org_id, member.membership_id, { role: nextRole }, user)
    await refresh()
  }

  async function remove(member: OrgMembership) {
    if (!user?.active_org_id) {
      return
    }
    if (!window.confirm(`Remove ${member.email} from this organization?`)) {
      return
    }
    await removeOrgMember(user.active_org_id, member.membership_id, user)
    await refresh()
  }

  async function resetActiveOrganizationData() {
    if (!user?.active_org_id || resetConfirm !== 'RESET_ORG_DATA') {
      return
    }
    if (!window.confirm('Reset all operational data for this organization? Members and invites will stay.')) {
      return
    }
    setResetBusy(true)
    setMessage(null)
    setResetSummary(null)
    try {
      const response = await resetOrganizationData(user.active_org_id, user)
      await refreshSession()
      await refresh()
      const deleted = Object.entries(response.deleted_counts)
        .filter(([, count]) => count > 0)
        .map(([key, count]) => `${key}: ${count}`)
        .join(', ')
      setResetSummary(deleted || 'No operational records were present.')
      setResetConfirm('')
      setMessage('Organization data reset complete.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Reset failed.')
    } finally {
      setResetBusy(false)
    }
  }

  if (!user?.is_host) {
    return (
      <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5 text-sm text-slate-300">
        Only the organization host can manage members.
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Organization</p>
        <h1 className="mt-2 text-3xl font-semibold">{organization?.name ?? 'Organization members'}</h1>
        <p className="mt-2 text-sm text-slate-400">Invite Gmail users, assign roles, and remove access from this NGO workspace.</p>
      </header>

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <h2 className="text-lg font-semibold">Create another organization</h2>
        <p className="mt-1 text-sm text-slate-400">
          Use this when you are hosting more than one NGO workspace. Data stays isolated per organization.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            className="rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-stone-100 outline-none"
            placeholder="New NGO organization name"
            value={newOrgName}
            onChange={(event) => setNewOrgName(event.target.value)}
          />
          <button
            className="rounded-2xl border border-white/10 px-4 py-3 text-sm font-semibold text-stone-100 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy || !newOrgName.trim()}
            onClick={() => void createAnotherOrganization()}
          >
            Create org
          </button>
        </div>
      </section>

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <h2 className="text-lg font-semibold">Invite member</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_240px_auto]">
          <input
            className="rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-stone-100 outline-none"
            placeholder="person@gmail.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <select
            className="rounded-2xl border border-white/10 bg-slate-950/70 px-3 py-3 text-sm text-stone-100"
            value={role}
            onChange={(event) => setRole(event.target.value as OrgRole)}
          >
            {roles.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <button
            className="rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy || !email.trim()}
            onClick={() => void invite()}
          >
            Invite
          </button>
        </div>
        {message ? <p className="mt-4 text-sm text-slate-300">{message}</p> : null}
      </section>

      <section className="grid gap-3">
        {members.map((member) => (
          <div key={member.membership_id} className="rounded-[1.25rem] border border-white/8 bg-slate-950/45 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-semibold text-stone-100">{member.email}</p>
                <p className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">{member.status}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className="rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm text-stone-100"
                  value={member.role}
                  disabled={member.role === 'HOST'}
                  onChange={(event) => void changeRole(member, event.target.value as OrgRole)}
                >
                  {(['HOST', ...roles] as OrgRole[]).map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
                <button
                  className="rounded-xl border border-rose-400/30 px-3 py-2 text-sm text-rose-200 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={member.role === 'HOST'}
                  onClick={() => void remove(member)}
                >
                  Remove
                </button>
              </div>
            </div>
          </div>
        ))}
      </section>

      {invites.length > 0 ? (
        <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
          <h2 className="text-lg font-semibold">Pending invites</h2>
          <div className="mt-4 grid gap-2">
            {invites.map((invite) => (
              <p key={invite.invite_id} className="text-sm text-slate-300">
                {invite.email} - {invite.role}
              </p>
            ))}
          </div>
        </section>
      ) : null}

      <section id="danger-zone" className="border border-white/12 bg-black p-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Danger zone</p>
        <h2 className="mt-2 text-xl font-semibold text-white">Reset organization data</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
          This removes incidents, teams, resources, dispatches, imports, graph runs, tokens, vectors, and evidence for the active
          organization. It keeps the organization, host account, members, and invites.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            className="border border-white/10 bg-black px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Type RESET_ORG_DATA"
            value={resetConfirm}
            onChange={(event) => setResetConfirm(event.target.value)}
          />
          <button
            className="border border-white/15 bg-white px-4 py-3 text-sm font-semibold text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={resetBusy || resetConfirm !== 'RESET_ORG_DATA'}
            onClick={() => void resetActiveOrganizationData()}
          >
            {resetBusy ? 'Resetting...' : 'Reset data'}
          </button>
        </div>
        {resetSummary ? <p className="mt-3 text-sm text-slate-300">Deleted {resetSummary}</p> : null}
      </section>
    </div>
  )
}
