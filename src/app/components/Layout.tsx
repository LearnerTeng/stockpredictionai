import {
  Bot,
  BriefcaseBusiness,
  CandlestickChart,
  FlaskConical,
  LayoutDashboard,
  Menu,
  Radar,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, useRouter } from '../router'

const navigation = [
  { to: '/', label: '总览', icon: LayoutDashboard, end: true },
  { to: '/recommendations', label: 'AI 推荐', icon: Radar },
  { to: '/portfolio', label: '我的组合', icon: BriefcaseBusiness },
  { to: '/assistant', label: 'AI 助手', icon: Bot },
  { to: '/trading', label: '模拟交易', icon: CandlestickChart },
  { to: '/image-lab', label: 'Image Lab', icon: FlaskConical },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const { navigate } = useRouter()

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault()
    const normalized = symbol.trim().toUpperCase()
    if (normalized) {
      navigate(`/stocks/${normalized}`)
      setSymbol('')
      setOpen(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark"><CandlestickChart size={20} /></div>
          <div><strong>TradingAI</strong><span>PRO WORKSPACE</span></div>
          <button className="icon-button mobile-only" onClick={() => setOpen(false)} aria-label="关闭菜单"><X /></button>
        </div>
        <div className="paper-badge"><ShieldCheck size={15} /> PAPER MODE · 模拟盘</div>
        <nav className="side-nav">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}>
              <Icon size={18} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="status-dot" /> API Gateway
          <small>localhost:8000</small>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-only" onClick={() => setOpen(true)} aria-label="打开菜单"><Menu /></button>
          <form className="symbol-search" onSubmit={submitSearch}>
            <Search size={17} />
            <input value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="搜索股票代码，例如 NVDA" />
            <kbd>Enter</kbd>
          </form>
          <div className="market-clock"><span>数据模式</span><strong>DEMO / DELAYED</strong></div>
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  )
}
