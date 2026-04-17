'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { useAuth } from '@/components/providers/auth-provider'

const navItems = [
  ['Command', '/command-center'],
  ['Cases', '/cases'],
  ['Dispatch', '/dispatch'],
  ['Teams', '/teams'],
  ['Volunteers', '/volunteers'],
  ['Resources', '/resources'],
  ['Imports', '/imports'],
  ['Analytics', '/analytics'],
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { user, logout, setActiveOrg } = useAuth()
  const visibleNavItems = user?.is_host ? [...navItems, ['Organization', '/organization']] : navItems

  return (
    <div className="min-h-screen text-stone-100">
      <div className="pointer-events-none fixed inset-0 bg-[linear-gradient(rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.04)_1px,transparent_1px)] bg-[size:56px_56px] opacity-35" />
      <div className="relative mx-auto grid min-h-screen max-w-[1720px] grid-cols-1 gap-2 px-2 py-2 lg:grid-cols-[236px_1fr]">
        <aside className="surface-card focus-outline motion-rise h-fit p-4 lg:sticky lg:top-2 lg:min-h-[calc(100vh-1rem)]">
          <div className="border-b border-white/8 pb-5">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-2xl border border-white/10 bg-white text-sm font-black text-slate-950">
                R
              </span>
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">ReliefOps</p>
                <h1 className="text-lg font-semibold tracking-[-0.03em] text-white">Command</h1>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-500">Minimal operations console for map-aware resource allocation.</p>
          </div>
          <nav className="minimal-scrollbar mt-5 flex gap-1.5 overflow-x-auto pb-1 lg:grid lg:overflow-visible lg:pb-0">
            {visibleNavItems.map(([label, href]) => {
              const active = pathname === href || pathname.startsWith(`${href}/`)
              return (
                <Link
                  key={href}
                  href={href}
                  className={`group flex shrink-0 items-center justify-between rounded-2xl border px-3.5 py-3 text-sm font-medium transition duration-300 lg:shrink ${
                    active
                      ? 'border-white/40 bg-white !text-black shadow-[inset_0_1px_0_rgba(255,255,255,0.4),0_12px_28px_rgba(255,255,255,0.08)]'
                      : 'border-transparent text-slate-400 hover:border-white/10 hover:bg-white/[0.045] hover:text-white'
                  }`}
                >
                  <span>{label}</span>
                  <span className={`h-1.5 w-1.5 rounded-full transition ${active ? 'bg-black' : 'bg-transparent group-hover:bg-slate-500'}`} />
                </Link>
              )
            })}
          </nav>
          <div className="mt-6 rounded-2xl border border-white/8 bg-black/20 p-4">
            {user?.organizations && user.organizations.length > 0 ? (
              <label className="mb-4 block text-[11px] uppercase tracking-[0.2em] text-slate-500">
                Organization
                <select
                  className="mt-2 w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm normal-case tracking-normal text-stone-100 outline-none transition focus:border-white/25"
                  value={user.active_org_id ?? ''}
                  onChange={(event) => setActiveOrg(event.target.value)}
                >
                  {user.organizations.map((org) => (
                    <option key={org.org_id} value={org.org_id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Operator</p>
            <p className="mt-2 truncate text-sm font-medium text-stone-100">{user?.email ?? user?.uid}</p>
            <p className="mt-1 text-xs text-slate-500">{user?.role}</p>
            <button
              className="mt-4 w-full rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:border-white/20 hover:bg-white/[0.03] hover:text-white"
              onClick={() => void logout()}
            >
              Sign out
            </button>
          </div>
        </aside>
        <main className="motion-fade min-w-0 rounded-[1.75rem] border border-white/18 bg-black/82 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_14px_42px_rgba(0,0,0,0.55)] ring-1 ring-white/[0.05] backdrop-blur-xl md:p-4">
          {children}
        </main>
      </div>
    </div>
  )
}
