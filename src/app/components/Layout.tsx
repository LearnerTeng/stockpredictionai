import {
  Bot,
  BriefcaseBusiness,
  CandlestickChart,
  FlaskConical,
  LayoutDashboard,
  Languages,
  Menu,
  Radar,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, useRouter } from '../router'
import { supportedLanguages, type AppLanguage } from '../i18n'

const navigation = [
  { to: '/', labelKey: 'nav.dashboard', icon: LayoutDashboard, end: true },
  { to: '/monitor', labelKey: 'nav.monitor', icon: Radar },
  { to: '/portfolio', labelKey: 'nav.portfolio', icon: BriefcaseBusiness },
  { to: '/assistant', labelKey: 'nav.assistant', icon: Bot },
  { to: '/trading', labelKey: 'nav.trading', icon: CandlestickChart },
  { to: '/image-lab', labelKey: 'nav.imageLab', icon: FlaskConical },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const { navigate } = useRouter()
  const { t, i18n } = useTranslation('common')
  const language = (i18n.resolvedLanguage ?? i18n.language) as AppLanguage

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
          <div><strong>TradingAI</strong><span>{t('brand.subtitle')}</span></div>
          <button className="icon-button mobile-only" onClick={() => setOpen(false)} aria-label={t('closeMenu')}><X /></button>
        </div>
        <div className="paper-badge"><ShieldCheck size={15} />{t('paperMode')}</div>
        <nav className="side-nav">
          {navigation.map(({ to, labelKey, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}>
              <Icon size={18} /><span>{t(labelKey)}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="status-dot" /> {t('apiGateway')}
          <small>localhost:8000</small>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-only" onClick={() => setOpen(true)} aria-label={t('openMenu')}><Menu /></button>
          <form className="symbol-search" onSubmit={submitSearch}>
            <Search size={17} />
            <input value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder={t('searchPlaceholder')} />
            <kbd>Enter</kbd>
          </form>
          <div className="topbar-tools">
            <label className="language-select" title={t('language')}>
              <Languages aria-hidden="true" />
              <select aria-label={t('language')} value={language} onChange={(event) => void i18n.changeLanguage(event.target.value)}>
                {supportedLanguages.map((value) => <option key={value} value={value}>{value === 'zh-CN' ? '中文' : value === 'ja' ? '日本語' : 'English'}</option>)}
              </select>
            </label>
            <div className="market-clock"><span>{t('dataMode')}</span><strong>DEMO / DELAYED</strong></div>
          </div>
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  )
}
