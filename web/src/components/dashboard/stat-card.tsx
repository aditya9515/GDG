import { Card, CardContent } from '@/components/ui/card'

export function StatCard({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string | number
  tone?: 'default' | 'alert'
}) {
  return (
    <Card
      className={`motion-rise overflow-hidden border-border/80 bg-card/88 shadow-sm transition duration-300 hover:-translate-y-0.5 hover:shadow-md ${
        tone === 'alert' ? 'status-critical' : ''
      }`}
    >
      <CardContent className="p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</p>
        <p className="mt-3 text-3xl font-semibold tracking-[-0.05em] text-foreground">{value}</p>
      </CardContent>
    </Card>
  )
}
