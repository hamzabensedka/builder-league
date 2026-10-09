/* Shared "How to use" panel for each challenge tab.
   Beginner-facing: 3–5 numbered steps, plain language, no jargon. */
export default function HowTo({ title = 'How to use', steps }) {
  return (
    <div className="card p-5 mb-4 fade-up">
      <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-3">
        {title}
      </p>
      <ol className="space-y-1.5">
        {steps.map((s, i) => (
          <li key={i} className="text-[13px] leading-snug flex items-baseline gap-2.5">
            <span className="mono text-[10px] text-[var(--ink-soft)] shrink-0">
              {String(i + 1).padStart(2, '0')}
            </span>
            <span className="text-[var(--ink)]">{s}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
