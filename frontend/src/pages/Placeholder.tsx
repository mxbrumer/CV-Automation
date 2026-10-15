export default function Placeholder({ title, plan }: { title: string; plan?: string }) {
  return (
    <section>
      <h1 className="text-xl font-semibold">{title}</h1>
      {plan && <p className="mt-2 text-muted">Built in plan {plan}.</p>}
    </section>
  )
}
