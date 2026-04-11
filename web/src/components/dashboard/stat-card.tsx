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
    <div
      className={`rounded-[1.5rem] border p-4 ${
        tone === 'alert'
          ? 'border-rose-400/20 bg-rose-500/8'
          : 'border-white/8 bg-slate-950/45'
      }`}
    >
      <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-semibold text-stone-100">{value}</p>
    </div>
  )
}
