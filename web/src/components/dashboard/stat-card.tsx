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
      className={`surface-card motion-rise p-4 transition duration-300 hover:-translate-y-0.5 ${
        tone === 'alert'
          ? 'border-white/28 bg-white/[0.06]'
          : ''
      }`}
    >
      <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.05em] text-white">{value}</p>
    </div>
  )
}
