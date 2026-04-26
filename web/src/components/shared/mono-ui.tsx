import type React from 'react'
import { AlertCircle, CheckCircle2, Circle, HelpCircle, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function PageHeader({
  eyebrow,
  title,
  description,
  children,
  about,
  className,
}: {
  eyebrow: string
  title: React.ReactNode
  description?: React.ReactNode
  children?: React.ReactNode
  about?: React.ReactNode
  className?: string | undefined
}) {
  return (
    <Card className={cn('motion-rise border-border/80 bg-card/95 shadow-sm', className)}>
      <CardHeader className="gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">{eyebrow}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <h1 className="text-3xl font-semibold tracking-[-0.05em] text-foreground sm:text-4xl">
              {title}
            </h1>
            {about ? <AboutButton>{about}</AboutButton> : null}
          </div>
          <div className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {description ? <div className="min-w-0">{description}</div> : null}
          </div>
        </div>
        {children ? <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap md:justify-end">{children}</div> : null}
      </CardHeader>
    </Card>
  )
}

export function SectionCard({
  eyebrow,
  title,
  description,
  children,
  action,
  about,
  className,
}: {
  eyebrow?: string
  title?: string
  description?: React.ReactNode
  children?: React.ReactNode
  action?: React.ReactNode
  about?: React.ReactNode
  className?: string
}) {
  return (
    <Card className={cn('border-border/80 bg-card/95 shadow-sm', className)}>
      {(eyebrow || title || description || action) ? (
        <CardHeader className="gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              {eyebrow ? <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">{eyebrow}</p> : null}
              {!title && about ? <AboutButton>{about}</AboutButton> : null}
            </div>
            {title ? (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-semibold tracking-[-0.03em] text-foreground">{title}</h2>
                {about ? <AboutButton>{about}</AboutButton> : null}
              </div>
            ) : null}
            <div className="mt-1 text-sm leading-6 text-muted-foreground">
              {description ? <div className="min-w-0">{description}</div> : null}
            </div>
          </div>
          {action}
        </CardHeader>
      ) : null}
      {children ? <CardContent>{children}</CardContent> : null}
    </Card>
  )
}

export function AboutButton({ children }: { children: React.ReactNode }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="About this section"
            className="shrink-0 rounded-full"
          >
            <HelpCircle className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-sm leading-5" side="top" align="start">
          {children}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export function MetricCard({
  label,
  value,
  note,
  state = 'neutral',
}: {
  label: string
  value: string | number
  note?: React.ReactNode
  state?: MonoState
}) {
  return (
    <div className={cn('rounded-2xl border p-4', monoSurfaceClass(state))}>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] opacity-70">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.05em]">{value}</p>
      {note ? <div className="mt-1 text-sm opacity-75">{note}</div> : null}
    </div>
  )
}

export type MonoState = 'neutral' | 'strong' | 'warning' | 'danger' | 'success' | 'muted'

export function MonoStatusBadge({
  children,
  state = 'neutral',
  className,
}: {
  children: React.ReactNode
  state?: MonoState
  className?: string
}) {
  const Icon = state === 'danger' ? XCircle : state === 'warning' ? AlertCircle : state === 'success' ? CheckCircle2 : Circle
  return (
    <Badge variant="outline" className={cn('gap-1 rounded-full uppercase tracking-[0.12em]', monoBadgeClass(state), className)}>
      <Icon className="size-3" />
      {children}
    </Badge>
  )
}

export function FilterPill({
  active,
  children,
  className,
  ...props
}: React.ComponentProps<'button'> & { active?: boolean }) {
  return (
    <Button
      variant={active ? 'default' : 'outline'}
      size="sm"
      className={cn('rounded-full uppercase tracking-[0.12em]', className)}
      {...props}
    >
      {children}
    </Button>
  )
}

export function monoStateFromToken(value: string | null | undefined): MonoState {
  const normalized = String(value ?? '').toUpperCase()
  if (['CRITICAL', 'HIGH', 'BLOCKED', 'UNASSIGNED', 'FAILED', 'ERROR', 'DELETED', 'REMOVED'].includes(normalized)) {
    return 'danger'
  }
  if (['MEDIUM', 'PARTIAL', 'WAITING', 'NEEDS_REVIEW', 'POSSIBLE_DUPLICATE', 'UNKNOWN'].includes(normalized)) {
    return 'warning'
  }
  if (['LOW', 'ASSIGNED', 'CONFIRMED', 'COMMITTED', 'COMPLETED', 'AVAILABLE', 'READY', 'SUCCESS'].includes(normalized)) {
    return 'success'
  }
  return 'neutral'
}

function monoSurfaceClass(state: MonoState) {
  switch (state) {
    case 'strong':
      return 'border-foreground bg-foreground text-background'
    case 'danger':
      return 'border-foreground bg-foreground text-background dark:border-foreground dark:bg-foreground dark:text-background'
    case 'warning':
      return 'border-foreground/50 bg-foreground/[0.08] text-foreground'
    case 'success':
      return 'border-foreground/30 bg-foreground/[0.05] text-foreground'
    case 'muted':
      return 'border-border bg-muted/50 text-muted-foreground'
    case 'neutral':
    default:
      return 'border-border bg-background/70 text-foreground'
  }
}

function monoBadgeClass(state: MonoState) {
  switch (state) {
    case 'danger':
      return 'border-foreground bg-foreground text-background'
    case 'warning':
      return 'border-foreground/50 bg-foreground/[0.08] text-foreground'
    case 'success':
      return 'border-foreground/30 bg-background text-foreground'
    case 'muted':
      return 'border-border text-muted-foreground'
    case 'strong':
      return 'border-foreground bg-foreground text-background'
    case 'neutral':
    default:
      return 'border-border text-foreground'
  }
}
