/** Shown wherever Low/High flags are shown (Principle 1: flag and explain, never diagnose). */
export function NotDiagnosis() {
  return (
    <p className="max-w-prose text-sm text-muted">
      Low and High only mean the value is outside the range printed by the lab. They are not a
      diagnosis; talk to your doctor about what your results mean.
    </p>
  )
}
