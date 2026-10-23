import {
  ArrowRight,
  BarChart3,
  Blocks,
  Download,
  LockKeyhole,
  Moon,
  Sparkles,
  Sun,
} from 'lucide-react'
import { Link } from 'react-router'
import { Footer } from '@/components/layout/Footer'
import { Button } from '@/components/ui/button'
import { useThemeStore } from '@/stores/themeStore'

const features = [
  {
    icon: LockKeyhole,
    title: 'Your own broker credentials',
    text: 'Keep your credentials, paper orders and reports together in your own account.',
  },
  {
    icon: BarChart3,
    title: 'Paper trading & positions',
    text: 'Review simulated positions, realized P&L and manually refreshed quote snapshots.',
  },
  {
    icon: Blocks,
    title: 'Visual strategy drafts',
    text: 'Organize workflow drafts visually before moving toward execution.',
  },
  {
    icon: Download,
    title: 'Order history & P&L exports',
    text: 'Filter paper order history by date and export orders, positions and daily P&L.',
  },
]

// Decorative sample candles: not a market feed or historical price series.
const candles = [
  172, 164, 181, 151, 142, 157, 131, 118, 139, 122, 105, 114, 93, 109, 121, 99, 87, 104, 79, 65, 83,
  72, 56, 75, 61, 43, 55, 69, 48, 38,
]

function TradingDeskPreview() {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-700/80 bg-[#0d1625] shadow-2xl shadow-black/40">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4 text-sm">
        <div className="flex items-center gap-3">
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
          <span className="font-semibold text-white">DOMAINXPERT / TERMINAL</span>
        </div>
        <span className="text-[10px] uppercase tracking-widest text-slate-400">
          Illustrative preview
        </span>
      </div>
      <div className="grid sm:grid-cols-[1fr_145px]">
        <div className="min-w-0 border-slate-800 p-5 sm:border-r">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold text-white">
                BHEL <span className="ml-2 text-xs font-normal text-slate-400">NSE</span>
              </p>
              <p className="mt-1 text-xs text-slate-500">Sample candlestick chart</p>
            </div>
            <span className="rounded border border-slate-700 px-2 py-1 text-xs text-emerald-400">
              5m
            </span>
          </div>
          <svg
            viewBox="0 0 390 255"
            className="mt-6 w-full"
            role="img"
            aria-label="Illustrative candlestick chart with volume bars. Not live market data."
          >
            {[35, 80, 125, 170, 215].map((y) => (
              <line key={y} x1="0" x2="390" y1={y} y2={y} stroke="#1e293b" strokeDasharray="3 5" />
            ))}
            {candles.map((y, i) => {
              const up = i % 4 !== 2
              const color = up ? '#34d399' : '#fb7185'
              return (
                <g key={i}>
                  <line x1={8 + i * 13} x2={8 + i * 13} y1={y - 13} y2={y + 22} stroke={color} />
                  <rect
                    x={4 + i * 13}
                    y={y}
                    width="8"
                    height={(i % 3) * 4 + 8}
                    rx="1"
                    fill={color}
                  />
                  <rect
                    x={4 + i * 13}
                    y={240 - (i % 5) * 4}
                    width="8"
                    height={12 + (i % 5) * 4}
                    fill={color}
                    opacity="0.3"
                  />
                </g>
              )
            })}
            <text x="0" y="254" fill="#64748b" fontSize="8">
              09:15
            </text>
            <text x="175" y="254" fill="#64748b" fontSize="8">
              12:00
            </text>
            <text x="355" y="254" fill="#64748b" fontSize="8">
              15:30
            </text>
          </svg>
        </div>
        <div className="hidden p-4 sm:block">
          <p className="mb-5 text-[10px] uppercase tracking-widest text-slate-500">Market watch</p>
          {['BHEL', 'RELIANCE', 'HDFCBANK', 'INFY', 'TCS'].map((name, i) => (
            <div key={name} className="border-b border-slate-800 py-4">
              <p className="text-xs font-medium text-slate-200">{name}</p>
              <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500">
                <span>NSE · Equity</span>
                <svg
                  aria-hidden="true"
                  viewBox="0 0 34 14"
                  className={i % 2 ? 'h-3 w-8 text-rose-400' : 'h-3 w-8 text-emerald-400'}
                >
                  <path
                    d={
                      i % 2
                        ? 'M0 3 L8 5 L14 2 L21 10 L28 8 L34 13'
                        : 'M0 12 L8 9 L14 11 L21 4 L28 6 L34 1'
                    }
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  />
                </svg>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 border-t border-slate-800 text-center text-[10px] uppercase tracking-wider text-slate-400">
        <span className="border-r border-slate-800 py-4">Paper positions</span>
        <span className="border-r border-slate-800 py-4">Order history</span>
        <span className="py-4">Daily P&amp;L</span>
      </div>
    </div>
  )
}

export default function Home() {
  const { mode, toggleMode } = useThemeStore()
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
        <nav
          aria-label="Main navigation"
          className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-5 py-4 sm:px-8"
        >
          <Link to="/" aria-label="DomainXpert Trade home">
            <img
              src="/images/domainxpert-trade.png"
              alt="DomainXpert Trade"
              className="h-9 w-auto max-w-[160px] rounded bg-white px-1 sm:max-w-[210px]"
            />
          </Link>
          <div className="flex items-center gap-2 sm:gap-4">
            <a
              href="#workspace"
              className="hidden text-sm text-muted-foreground hover:text-foreground md:block"
            >
              Platform
            </a>
            <a
              href="#pricing"
              className="hidden text-sm text-muted-foreground hover:text-foreground md:block"
            >
              Pricing
            </a>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleMode}
              aria-label="Toggle color theme"
            >
              {mode === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" asChild>
              <Link to="/login">Sign in</Link>
            </Button>
          </div>
        </nav>
      </header>
      <main className="flex-1">
        <section className="relative overflow-hidden border-b border-slate-800 bg-[#080f1c] text-white">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_75%_30%,rgba(16,185,129,0.12),transparent_55%)]"
          />
          <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-5 py-16 sm:px-8 sm:py-24 lg:grid-cols-[0.9fr_1.1fr] lg:py-28">
            <div>
              <p className="mb-6 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-400">
                <span className="h-px w-8 bg-emerald-400" />
                DomainXpert Trade / Building AI-assisted trading
              </p>
              <h1 className="text-5xl font-semibold leading-[1.06] tracking-tight sm:text-6xl lg:text-7xl">
                AI-assisted trading.
                <br />
                Your strategy.
                <br />
                <span className="text-emerald-400">Your control.</span>
              </h1>
              <p className="mt-7 max-w-lg text-lg leading-relaxed text-slate-400">
                We’re building a trading workspace that combines AI-assisted market research,
                strategy exploration and paper trading review. Develop your approach with clear data
                and keep control of every trading decision.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button
                  size="lg"
                  asChild
                  className="bg-emerald-400 font-semibold text-slate-950 hover:bg-emerald-300"
                >
                  <Link to="/signup">
                    Start your trading journey <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
                <Button
                  size="lg"
                  variant="outline"
                  asChild
                  className="border-slate-700 bg-transparent text-white hover:bg-slate-800 hover:text-white"
                >
                  <a href="#workspace">Explore the platform</a>
                </Button>
              </div>
              <div className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-400">
                <span>Paper trading</span>
                <span>Market data</span>
                <span>Performance reports</span>
              </div>
              <p className="mt-5 max-w-md text-[11px] leading-relaxed text-slate-500">
                AI features are planned and not active in this preview. Live trading is disabled.
                Trading involves risk; paper results do not guarantee real returns.
              </p>
            </div>
            <TradingDeskPreview />
          </div>
          <div className="relative border-t border-slate-800">
            <div className="mx-auto flex max-w-7xl flex-wrap justify-between gap-5 px-5 py-5 font-mono text-[11px] uppercase tracking-widest text-slate-400 sm:px-8">
              <span>01 / Read the market</span>
              <span>02 / Practice with purpose</span>
              <span>03 / Review every session</span>
            </div>
          </div>
        </section>
        <section
          id="workspace"
          className="mx-auto max-w-7xl scroll-mt-24 px-5 py-16 sm:px-8 sm:py-24"
        >
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-600 dark:text-emerald-400">
            Your trading toolkit
          </p>
          <h2 className="mt-4 max-w-xl text-3xl font-semibold tracking-tight sm:text-4xl">
            From market view to trading review.
          </h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2">
            {features.map(({ icon: Icon, title, text }) => (
              <article key={title} className="rounded-2xl border p-6 sm:p-8">
                <Icon
                  aria-hidden="true"
                  className="mb-6 h-6 w-6 text-emerald-600 dark:text-emerald-400"
                />
                <h3 className="text-xl font-semibold">{title}</h3>
                <p className="mt-3 max-w-lg leading-relaxed text-muted-foreground">{text}</p>
              </article>
            ))}
          </div>
          <p className="mt-8 text-sm leading-relaxed text-muted-foreground">
            Market data may be delayed or unavailable. Simulated results exclude real execution
            conditions and do not guarantee future performance.
          </p>
        </section>
        <section id="ai" className="border-t bg-muted/20 px-5 py-16 sm:px-8">
          <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-2 lg:items-center">
            <div>
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-600 dark:text-emerald-400">
                <Sparkles className="h-4 w-4" /> AI research roadmap
              </p>
              <h2 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">
                Trading first.
                <br />
                AI alongside.
              </h2>
              <p className="mt-5 max-w-lg leading-relaxed text-muted-foreground">
                A research assistant designed to help you ask questions about market data, explore
                strategy ideas and review paper trading results. You stay in control of every
                trading decision.
              </p>
              <p className="mt-4 text-sm font-medium text-amber-700 dark:text-amber-400">
                Planned for DomainXpert accounts. Not enabled in the current preview or included as
                an active feature in this plan.
              </p>
            </div>
            <div className="rounded-2xl border bg-card p-6 sm:p-8">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold">DomainXpert AI</span>
                <span className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
                  Concept preview
                </span>
              </div>
              <p className="mt-6 text-xs uppercase tracking-widest text-muted-foreground">
                Questions you could explore
              </p>
              <ul className="mt-4 space-y-3 text-sm">
                <li className="rounded-xl border p-4">
                  “Help me understand this candlestick pattern.”
                </li>
                <li className="rounded-xl border p-4">
                  “Explain the assumptions in my strategy draft.”
                </li>
                <li className="rounded-xl border p-4">“Summarize my paper trading results.”</li>
              </ul>
              <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
                Illustrative prompts, not generated analysis. AI can make mistakes; it does not
                guarantee returns or replace your judgment.
              </p>
            </div>
          </div>
        </section>
        <section id="pricing" className="border-t bg-muted/20 px-5 py-16 sm:px-8">
          <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-2 lg:items-center">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-600 dark:text-emerald-400">
                Simple monthly membership
              </p>
              <h2 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">
                One plan. Your complete paper workspace.
              </h2>
              <p className="mt-5 max-w-lg leading-relaxed text-muted-foreground">
                One account for your trading process. Create your account to see payment
                instructions and the features available in your workspace.
              </p>
            </div>
            <div className="rounded-2xl border bg-card p-7 sm:p-10">
              <h3 className="text-xl font-semibold">DomainXpert Trade</h3>
              <p className="mt-5 text-5xl font-semibold tracking-tight">
                ₹2,360<span className="text-base font-normal text-muted-foreground"> / month</span>
              </p>
              <p className="mt-3 text-sm text-muted-foreground">
                No GST charged separately. Access begins after payment verification. No automatic
                renewal.
              </p>
              <ul className="my-7 space-y-3 text-sm">
                <li>✓ Personal account and broker setup</li>
                <li>✓ Paper order history and performance reports</li>
                <li>✓ CSV exports for your records</li>
              </ul>
              <Button
                size="lg"
                asChild
                className="w-full bg-emerald-600 text-white hover:bg-emerald-700"
              >
                <Link to="/signup">
                  Get started <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                Access starts after payment approval when subscriptions are enabled. Broker charges
                are separate. Restricted preview does not enable live trading.
              </p>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  )
}
