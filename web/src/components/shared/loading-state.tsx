type LoadingStateProps = {
  title?: string
  message?: string
  compact?: boolean
}

export function InlineLoading({ label = 'Working' }: { label?: string }) {
  return (
    <span className="inline-flex items-center justify-center gap-2">
      <span className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
      <span>{label}</span>
    </span>
  )
}

export function LoadingState({
  title = 'Loading workspace',
  message = 'Getting the latest operational data ready.',
  compact = false,
}: LoadingStateProps) {
  return (
    <div className={`motion-rise flex items-center justify-center ${compact ? 'min-h-[180px]' : 'min-h-screen'} text-muted-foreground`}>
      <div className="w-full max-w-md rounded-3xl border border-border bg-card/90 p-6 text-center shadow-xl backdrop-blur">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-border bg-primary/10 text-primary">
          <span className="h-5 w-5 animate-spin rounded-full border-2 border-current border-t-transparent" />
        </div>
        <p className="mt-4 text-sm font-semibold uppercase tracking-[0.18em] text-foreground">{title}</p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{message}</p>
      </div>
    </div>
  )
}

export function BusyOverlay({
  active,
  title = 'Updating',
  message = 'Please hold while ReliefOps refreshes this view.',
}: LoadingStateProps & { active: boolean }) {
  if (!active) {
    return null
  }

  return (
    <div className="absolute inset-0 z-20 flex items-start justify-center bg-background/70 px-4 py-8 backdrop-blur-sm">
      <div className="pointer-events-auto w-full max-w-sm rounded-3xl border border-border bg-card/95 p-5 text-center shadow-xl">
        <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full border border-border bg-primary/10 text-primary">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        </div>
        <p className="mt-3 text-xs font-semibold uppercase tracking-[0.2em] text-foreground">{title}</p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{message}</p>
      </div>
    </div>
  )
}
