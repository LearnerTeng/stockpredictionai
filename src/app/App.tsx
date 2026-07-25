import { lazy, Suspense } from 'react'
import { Layout } from './components/Layout'
import { LoadingPanel } from './components/UI'
import { useRouter } from './router'

const AssistantPage = lazy(() => import('./pages/AssistantPage').then((module) => ({ default: module.AssistantPage })))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const ImageLabPage = lazy(() => import('./pages/ImageLabPage').then((module) => ({ default: module.ImageLabPage })))
const PortfolioPage = lazy(() => import('./pages/PortfolioPage').then((module) => ({ default: module.PortfolioPage })))
const RecommendationsPage = lazy(() => import('./pages/RecommendationsPage').then((module) => ({ default: module.RecommendationsPage })))
const StockPage = lazy(() => import('./pages/StockPage').then((module) => ({ default: module.StockPage })))
const TradingPage = lazy(() => import('./pages/TradingPage').then((module) => ({ default: module.TradingPage })))

export function App() {
  const { path } = useRouter()
  let page: React.ReactNode
  if (path === '/') page = <DashboardPage />
  else if (path === '/recommendations') page = <RecommendationsPage />
  else if (path === '/portfolio') page = <PortfolioPage />
  else if (path === '/assistant') page = <AssistantPage />
  else if (path === '/trading') page = <TradingPage />
  else if (path === '/image-lab') page = <ImageLabPage />
  else if (path.startsWith('/stocks/')) {
    page = <StockPage symbol={decodeURIComponent(path.slice('/stocks/'.length)).toUpperCase()} />
  } else page = <DashboardPage />

  return (
    <Suspense fallback={<LoadingPanel label="正在加载工作台模块" />}>
      <Layout>{page}</Layout>
    </Suspense>
  )
}
