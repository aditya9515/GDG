'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { InlineLoading } from '@/components/shared/loading-state'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { createOrganization } from '@/lib/api'

export default function CreateOrganizationPage() {
  const router = useRouter()
  const { user, setActiveOrg, refreshSession } = useAuth()
  const [name, setName] = useState('ReliefOps Demo NGO')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!user || !name.trim()) {
      return
    }
    setBusy(true)
    setMessage('Creating organization and assigning host access...')
    try {
      const response = await createOrganization(name, user)
      setActiveOrg(response.organization.org_id)
      await refreshSession()
      setActiveOrg(response.organization.org_id)
      setMessage('Organization created. Opening command center.')
      router.replace('/command-center')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create organization.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card className="border-border/80 bg-card/90 shadow-sm">
        <CardHeader>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Host onboarding</p>
          <CardTitle className="text-3xl tracking-[-0.04em]">Create your NGO organization</CardTitle>
          <CardDescription>
            The creator becomes the host. Hosts can view members, change roles, remove access, and manage organization data.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Label htmlFor="org-name">Organization name</Label>
          <Input id="org-name" className="mt-3 h-11 rounded-xl" value={name} onChange={(event) => setName(event.target.value)} />
          <Button className="mt-4 h-11 rounded-xl" disabled={busy || !name.trim()} onClick={() => void submit()}>
            {busy ? <InlineLoading label="Creating" /> : 'Create organization'}
          </Button>
          {message ? (
            <Alert className="mt-4">
              <AlertDescription>{message}</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
