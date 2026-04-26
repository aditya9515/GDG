'use client'

import { useEffect, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { AboutButton, SectionCard } from '@/components/shared/mono-ui'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  createOrganization,
  getOrganizationMembers,
  removeOrgMember,
  resetOrganizationData,
  updateOrgMember,
} from '@/lib/api'
import type { OrgMembership, OrgRole, Organization } from '@/lib/types'

const roles: OrgRole[] = ['INCIDENT_COORDINATOR', 'MEDICAL_COORDINATOR', 'LOGISTICS_LEAD', 'VIEWER']

export default function OrganizationPage() {
  const { user, setActiveOrg, refreshSession } = useAuth()
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [members, setMembers] = useState<OrgMembership[]>([])
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
    if (!window.confirm('Reset all operational data for this organization? Members will stay.')) {
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
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-3xl font-semibold">{organization?.name ?? 'Organization members'}</h1>
          <AboutButton>
            Organization settings control the active NGO workspace, member access, role permissions, and high-risk data reset actions for this organization only.
          </AboutButton>
        </div>
        <p className="mt-2 text-sm text-slate-400">Manage members, assign roles, and remove access.</p>
      </header>

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Create another organization</h2>
          <AboutButton>
            Create a separate workspace when you need to manage a different NGO, district, drill, or deployment without mixing incidents, teams, and resources.
          </AboutButton>
        </div>
        <p className="mt-1 text-sm text-slate-400">
          Use this when you are hosting more than one NGO workspace.
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

        {message ? <p className="mt-4 text-sm text-slate-300">{message}</p> : null}
      </section>

      <section className="grid gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Active members</h2>
          <AboutButton>
            Members listed here have access to the active organization. Roles determine what they can review, plan, or manage inside the workspace.
          </AboutButton>
        </div>
        {members.map((member) => (
          <div
            key={member.membership_id}
            className="rounded-[1.25rem] border border-white/8 bg-slate-950/45 p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-semibold text-stone-100">{member.email}</p>
                <p className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                  {member.status}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  className="rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm text-stone-100"
                  value={member.role}
                  disabled={member.role === 'HOST'}
                  onChange={(event) =>
                    void changeRole(member, event.target.value as OrgRole)
                  }
                >
                  {(['HOST', ...roles] as OrgRole[]).map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>

                <button
                  className="rounded-xl border border-foreground/30 px-3 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-40"
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

      <section id="danger-zone">
        <SectionCard
          eyebrow="Danger zone"
          title="Reset organization data"
          description="This removes incidents, teams, resources, dispatches, imports, graph runs, tokens, vectors, and evidence for the active organization."
          about="This destructive area deletes operational records for the active organization. Members and the organization itself stay, but incidents, teams, resources, dispatches, imports, graph runs, tokens, vectors, and evidence are removed."
          className="border-foreground/30 bg-card"
        >
          <div className="grid gap-3 md:grid-cols-[1fr_auto]">
            <Input
              placeholder="Type RESET_ORG_DATA"
              value={resetConfirm}
              onChange={(event) => setResetConfirm(event.target.value)}
            />

            <Button
              className="uppercase tracking-[0.12em]"
              disabled={resetBusy || resetConfirm !== 'RESET_ORG_DATA'}
              onClick={() => void resetActiveOrganizationData()}
            >
              {resetBusy ? 'Resetting...' : 'Reset data'}
            </Button>
          </div>

          {resetSummary ? (
            <p className="mt-3 text-sm text-muted-foreground">Deleted {resetSummary}</p>
          ) : null}
        </SectionCard>
      </section>
    </div>
  )
}
