import React from 'react'
import type { UrgencyKind } from '@/lib/types'

const styles: Record<UrgencyKind, string> = {
  CRITICAL: 'bg-white text-black border-white shadow-[0_0_24px_rgba(255,255,255,0.12)]',
  HIGH: 'bg-zinc-200/14 text-zinc-100 border-white/30',
  MEDIUM: 'bg-zinc-500/12 text-zinc-200 border-white/20',
  LOW: 'bg-zinc-700/22 text-zinc-300 border-white/14',
  UNKNOWN: 'bg-white/[0.04] text-zinc-400 border-white/12',
}

export function UrgencyBadge({ urgency }: { urgency: UrgencyKind }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-[0.18em] ${styles[urgency]}`}>
      {urgency}
    </span>
  )
}
