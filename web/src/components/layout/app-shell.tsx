'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type React from 'react'
import {
  Building2,
  ClipboardList,
  HeartPulse,
  Home,
  LogOut,
  MapPinned,
  Menu,
  Package,
  RadioTower,
  UploadCloud,
  Users,
} from 'lucide-react'

import { SystemStatusPanel } from '@/components/layout/system-status-panel'
import { useAuth } from '@/components/providers/auth-provider'
import { ModeToggle } from '@/components/shared/mode-toggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { humanizeToken } from '@/lib/format'

const navItems = [
  { label: 'Command', href: '/command-center', icon: Home },
  { label: 'Imports', href: '/imports', icon: UploadCloud },
  { label: 'Cases', href: '/cases', icon: ClipboardList },
  { label: 'Teams', href: '/teams', icon: Users },
  { label: 'Resources', href: '/resources', icon: Package },
  { label: 'Volunteers', href: '/volunteers', icon: HeartPulse },
  { label: 'Dispatch', href: '/dispatch', icon: RadioTower },
]

const hostNavItem = { label: 'Organization', href: '/organization', icon: Building2 }

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { user, logout, setActiveOrg } = useAuth()
  const visibleNavItems = user?.is_host ? [...navItems, hostNavItem] : navItems
  const current = visibleNavItems.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))

  const nav = <NavigationItems items={visibleNavItems} pathname={pathname} />

  return (
    <div className="min-h-screen text-foreground">
      <div className="pointer-events-none fixed inset-0 hairline-grid opacity-45" />
      <div className="pointer-events-none fixed inset-x-0 top-0 h-56 bg-gradient-to-b from-primary/10 to-transparent" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-[1760px] flex-col gap-3 px-3 py-3 lg:grid lg:grid-cols-[280px_minmax(0,1fr)] lg:gap-4 lg:px-4">
        <header className="surface-card sticky top-3 z-30 flex items-center justify-between gap-3 p-3 lg:hidden">
          <div className="flex min-w-0 items-center gap-3">
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="outline" size="icon" className="shrink-0 rounded-xl" aria-label="Open navigation">
                  <Menu className="size-4" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[min(340px,88vw)] border-sidebar-border bg-sidebar p-0" dir="ltr">
                <SheetHeader className="border-b border-sidebar-border px-5 py-4 text-start">
                  <SheetTitle className="flex items-center gap-3">
                    <BrandMark />
                    <span>ReliefOps</span>
                  </SheetTitle>
                </SheetHeader>
                <ScrollArea className="h-[calc(100vh-5rem)] px-4 py-4">
                  {nav}
                  <Separator className="my-4" />
                  <AccountPanel compact />
                </ScrollArea>
              </SheetContent>
            </Sheet>
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">ReliefOps</p>
              <h1 className="truncate text-base font-semibold">{current?.label ?? 'Operations'}</h1>
            </div>
          </div>
          <ModeToggle />
        </header>

        <aside className="surface-card focus-outline motion-rise hidden h-fit min-w-0 p-4 lg:sticky lg:top-4 lg:block lg:min-h-[calc(100vh-2rem)]">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <BrandMark />
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">ReliefOps</p>
                <h1 className="text-lg font-semibold tracking-[-0.03em]">Command</h1>
              </div>
            </div>
            <ModeToggle />
          </div>
          <p className="mt-4 text-sm leading-6 text-muted-foreground">
            Clinical-grade disaster operations for intake, mapping, resource planning, and dispatch confirmation.
          </p>

          <Separator className="my-5" />
          <ScrollArea className="h-[calc(100vh-23rem)] pe-2">
            {nav}
          </ScrollArea>
          <Separator className="my-5" />
          <AccountPanel />
          <SystemStatusPanel />
        </aside>

        <main className="motion-fade min-w-0 rounded-3xl border border-border/70 bg-background/72 p-2 shadow-[0_20px_80px_color-mix(in_oklch,var(--foreground)_10%,transparent)] backdrop-blur-xl sm:p-3 md:p-4">
          {children}
        </main>
      </div>
    </div>
  )

  function AccountPanel({ compact = false }: { compact?: boolean }) {
    return (
      <div className="rounded-2xl border border-border/80 bg-card/75 p-3 shadow-sm">
        {user?.organizations && user.organizations.length > 0 ? (
          <label className="block text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Organization
            <Select value={user.active_org_id ?? ''} onValueChange={setActiveOrg}>
              <SelectTrigger className="mt-2 h-10 rounded-xl bg-background/70 text-start">
                <SelectValue placeholder="Select organization" />
              </SelectTrigger>
              <SelectContent dir="ltr">
                {user.organizations.map((org) => (
                  <SelectItem key={org.org_id} value={org.org_id}>
                    {org.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        ) : null}

        <div className={compact ? 'mt-4' : 'mt-5'}>
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Operator</p>
            {user?.is_host ? <Badge variant="secondary">Host</Badge> : null}
          </div>
          <p className="mt-2 truncate text-sm font-semibold">{user?.email ?? user?.uid}</p>
          <p className="mt-1 text-xs text-muted-foreground">{humanizeToken(user?.role ?? 'operator')}</p>
          <Button variant="outline" className="mt-4 w-full justify-start gap-2 rounded-xl" onClick={() => void logout()}>
            <LogOut className="size-4" />
            Sign out
          </Button>
        </div>
      </div>
    )
  }
}

function NavigationItems({
  items,
  pathname,
}: {
  items: Array<{ label: string; href: string; icon: React.ComponentType<{ className?: string }> }>
  pathname: string
}) {
  return (
    <nav className="grid gap-1.5">
      <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Workspace</p>
      {items.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
        const Icon = item.icon
        return (
          <Button
            key={item.href}
            asChild
            variant={active ? 'default' : 'ghost'}
            className={`h-11 justify-start gap-3 rounded-xl px-3 text-sm ${active ? 'light-surface shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
          >
            <Link href={item.href}>
              <Icon className="size-4" aria-hidden="true" />
              <span>{item.label}</span>
              {active ? <span className="ms-auto h-1.5 w-1.5 rounded-full bg-current" /> : null}
            </Link>
          </Button>
        )
      })}
    </nav>
  )
}

function BrandMark() {
  return (
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-primary text-sm font-black text-primary-foreground shadow-sm">
      <MapPinned className="size-5" aria-hidden="true" />
    </span>
  )
}
