'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { useAuth } from '@/components/providers/auth-provider'

const navItems = [
  ['Command Center', '/command-center'],
  ['Dispatch', '/dispatch'],
  ['Teams', '/teams'],
  ['Volunteers', '/volunteers'],
  ['Resources', '/resources'],
  ['Imports', '/imports'],
  ['Analytics', '/analytics'],
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(249,115,22,0.12),_transparent_40%),linear-gradient(180deg,#0d141c,#111827)] text-stone-100">
      <div className="mx-auto grid min-h-screen max-w-[1600px] grid-cols-1 gap-6 px-4 py-4 lg:grid-cols-[260px_1fr] lg:px-6">
        <aside className="rounded-[1.75rem] border border-white/8 bg-[rgba(13,19,27,0.88)] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.32)] backdrop-blur">
          <div className="border-b border-white/8 pb-5">
            <p className="text-xs uppercase tracking-[0.24em] text-amber-200/80">ReliefOps AI</p>
            <h1 className="mt-3 text-2xl font-semibold">Maps-First Ops</h1>
            <p className="mt-2 text-sm leading-6 text-slate-400">Geo-anchor incidents, teams, and resources for faster dispatch.</p>
          </div>
          <nav className="mt-6 grid gap-2">
            {navItems.map(([label, href]) => {
              const active = pathname === href || pathname.startsWith(`${href}/`)
              return (
                <Link
                  key={href}
                  href={href}
                  className={`rounded-2xl px-4 py-3 text-sm font-medium transition ${
                    active
                      ? 'bg-amber-300/12 text-amber-100 shadow-[inset_0_0_0_1px_rgba(253,186,116,0.28)]'
                      : 'text-slate-300 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  {label}
                </Link>
              )
            })}
          </nav>
          <div className="mt-8 rounded-2xl border border-white/8 bg-slate-950/60 p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Active operator</p>
            <p className="mt-2 text-sm font-medium text-stone-100">{user?.email ?? user?.uid}</p>
            <p className="mt-1 text-xs text-slate-500">{user?.role}</p>
            <button
              className="mt-4 rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:border-white/20 hover:text-white"
              onClick={logout}
            >
              Sign out
            </button>
          </div>
        </aside>
        <main className="rounded-[1.75rem] border border-white/8 bg-[rgba(14,20,28,0.88)] p-4 shadow-[0_24px_80px_rgba(0,0,0,0.32)] backdrop-blur md:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
