import React from 'react'
import type { UrgencyKind } from '@/lib/types'

const styles: Record<UrgencyKind, string> = {
  CRITICAL: 'bg-rose-500/15 text-rose-200 border-rose-500/30',
  HIGH: 'bg-orange-400/15 text-orange-100 border-orange-300/30',
  MEDIUM: 'bg-amber-300/15 text-amber-100 border-amber-300/30',
  LOW: 'bg-emerald-400/12 text-emerald-100 border-emerald-300/25',
  UNKNOWN: 'bg-slate-200/8 text-slate-200 border-white/10',
}

export function UrgencyBadge({ urgency }: { urgency: UrgencyKind }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold tracking-[0.18em] ${styles[urgency]}`}>
      {urgency}
    </span>
  )
}
