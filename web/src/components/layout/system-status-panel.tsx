'use client'

import { useEffect, useMemo, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { ENABLE_GOOGLE_MAPS_UI } from '@/lib/config'
import { getAiStatus, getHealth, getMe } from '@/lib/api'

type StatusState = {
  api: 'checking' | 'ok' | 'offline'
  auth: 'checking' | 'ok' | 'missing-org' | 'failed' | 'signed-out'
  ai: 'checking' | 'ok' | 'warning' | 'unknown'
  message: string
}

export function SystemStatusPanel() {
  const { user } = useAuth()
  const [status, setStatus] = useState<StatusState>({
    api: 'checking',
    auth: user ? 'checking' : 'signed-out',
    ai: user?.active_org_id ? 'checking' : 'unknown',
    message: 'Checking backend connection...',
  })

  useEffect(() => {
    let cancelled = false

    async function check() {
      setStatus({
        api: 'checking',
        auth: user ? 'checking' : 'signed-out',
        ai: user?.active_org_id ? 'checking' : 'unknown',
        message: 'Checking backend connection...',
      })

      try {
        await getHealth()
      } catch (error) {
        if (!cancelled) {
          setStatus({
            api: 'offline',
            auth: user ? 'failed' : 'signed-out',
            ai: 'unknown',
            message: error instanceof Error ? error.message : 'ReliefOps API is unreachable.',
          })
        }
        return
      }

      if (!user) {
        if (!cancelled) {
          setStatus({
            api: 'ok',
            auth: 'signed-out',
            ai: 'unknown',
            message: 'API online. Sign in to verify organization and AI provider status.',
          })
        }
        return
      }

      try {
        const profile = await getMe(user)
        if (!profile.active_org_id) {
          if (!cancelled) {
            setStatus({
              api: 'ok',
              auth: 'missing-org',
              ai: 'unknown',
              message: 'Signed in, but no active organization is selected.',
            })
          }
          return
        }

        const ai = await getAiStatus(user)
        const aiWarning =
          ai.provider_mode === 'gemini'
            ? !(ai.gemini_enabled && ai.gemini_configured)
            : ai.gemma4_enabled && !ai.ollama_reachable && !ai.gemini_configured && ai.provider_mode !== 'heuristic'
        if (!cancelled) {
          setStatus({
            api: 'ok',
            auth: 'ok',
            ai: aiWarning ? 'warning' : 'ok',
            message: `Org connected. AI ${ai.provider_mode}; fallback ${ai.fallback_order.join(' -> ')}; Gemma4 ${
              ai.gemma4_enabled ? 'enabled' : 'disabled'
            }.`,
          })
        }
      } catch (error) {
        if (!cancelled) {
          setStatus({
            api: 'ok',
            auth: 'failed',
            ai: 'unknown',
            message: error instanceof Error ? error.message : 'Session verification failed.',
          })
        }
      }
    }

    void check()
    return () => {
      cancelled = true
    }
  }, [user?.active_org_id, user?.mode, user?.token, user?.uid])

  const chips = useMemo(
    () => [
      { label: 'API', value: status.api },
      { label: 'Auth', value: status.auth },
      { label: 'AI', value: status.ai },
      { label: 'Maps UI', value: ENABLE_GOOGLE_MAPS_UI ? 'configured' : 'local map' },
    ],
    [status],
  )

  return (
    <details className="mt-4 rounded-2xl border border-white/8 bg-black/20 p-3">
      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
        System status
      </summary>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <span key={chip.label} className="rounded-xl border border-white/10 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-slate-400">
            {chip.label}: {chip.value}
          </span>
        ))}
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-500">{status.message}</p>
    </details>
  )
}
