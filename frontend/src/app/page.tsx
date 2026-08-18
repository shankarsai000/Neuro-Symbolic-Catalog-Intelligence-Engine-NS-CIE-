export default function Home() {
  return (
    <main className="min-h-screen bg-slate-50 px-6 py-10 text-slate-900">
      <div className="mx-auto max-w-5xl">
        <header className="mb-8 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium uppercase tracking-[0.2em] text-sky-700">
              NS-CIE
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight md:text-4xl">
              NS-CIE Enrichment Dashboard
            </h1>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
            Backend connected
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">Pipeline status</p>
            <p className="mt-2 text-2xl font-semibold">Ready</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">Queued jobs</p>
            <p className="mt-2 text-2xl font-semibold">0</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">Last sync</p>
            <p className="mt-2 text-2xl font-semibold">--</p>
          </div>
        </section>
      </div>
    </main>
  );
}
