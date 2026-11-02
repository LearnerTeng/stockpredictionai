import { createContext, type AnchorHTMLAttributes, type ReactNode, useContext, useEffect, useState } from 'react'

interface RouterValue {
  path: string
  location: string
  searchParams: URLSearchParams
  navigate: (path: string) => void
}

const RouterContext = createContext<RouterValue | null>(null)

function readLocation() {
  const value = window.location.hash.replace(/^#/, '') || '/'
  return value.startsWith('/') ? value : `/${value}`
}

export function RouterProvider({ children }: { children: ReactNode }) {
  const [location, setLocation] = useState(readLocation)
  useEffect(() => {
    const update = () => setLocation(readLocation())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  const navigate = (target: string) => {
    const normalized = target.startsWith('/') ? target : `/${target}`
    if (readLocation() !== normalized) window.location.hash = normalized
  }
  const [path, search = ''] = location.split('?', 2)
  return <RouterContext.Provider value={{ path, location, searchParams: new URLSearchParams(search), navigate }}>{children}</RouterContext.Provider>
}

export function useRouter() {
  const context = useContext(RouterContext)
  if (!context) throw new Error('useRouter must be used inside RouterProvider')
  return context
}

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string
}

export function Link({ to, onClick, ...props }: LinkProps) {
  return <a {...props} href={`#${to}`} onClick={(event) => { onClick?.(event); if (!event.defaultPrevented) event.currentTarget.blur() }} />
}

export function NavLink({ to, end = false, className = '', ...props }: LinkProps & { end?: boolean }) {
  const { path } = useRouter()
  const active = end ? path === to : path === to || path.startsWith(`${to}/`)
  return <Link {...props} to={to} className={`${className} ${active ? 'active' : ''}`.trim()} />
}
