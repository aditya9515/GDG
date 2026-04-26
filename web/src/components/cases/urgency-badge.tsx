import React from 'react'
import type { UrgencyKind } from '@/lib/types'
import { humanizeToken } from '@/lib/format'

function getUrgencyClass(urgency: UrgencyKind) {
  switch (urgency) {
    case 'CRITICAL':
      return 'border-foreground bg-foreground text-background'
    case 'HIGH':
      return 'border-foreground/70 bg-foreground/12 text-foreground'
    case 'MEDIUM':
      return 'border-foreground/40 bg-foreground/8 text-foreground'
    case 'LOW':
      return 'border-border bg-background text-foreground'
    case 'UNKNOWN':
    default:
      return 'border-border bg-muted text-muted-foreground'
  }
}

export function UrgencyBadge({ urgency }: { urgency: UrgencyKind }) {
  return (
    <span
      className={`inline-flex rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${getUrgencyClass(urgency)}`}
    >
      {humanizeToken(urgency)}
    </span>
  )
}
