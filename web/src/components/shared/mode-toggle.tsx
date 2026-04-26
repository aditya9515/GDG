'use client'

import { Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTheme } from 'next-themes'

import { Button } from '@/components/ui/button'

export function ModeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const dark = mounted ? resolvedTheme === 'dark' : true

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="gap-2 rounded-xl border-border/80 bg-background/70 text-xs font-semibold shadow-sm backdrop-blur"
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      onClick={() => setTheme(dark ? 'light' : 'dark')}
    >
      {dark ? <Sun className="size-4" aria-hidden="true" /> : <Moon className="size-4" aria-hidden="true" />}
      <span className="hidden sm:inline">{dark ? 'Light' : 'Dark'}</span>
    </Button>
  )
}
