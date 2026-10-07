import { useHashRoute } from './router'
import Dashboard from './pages/Dashboard'
import Browse from './pages/Browse'
import Compare from './pages/Compare'
import Explorer from './pages/Explorer'
import './app.css'

function Page({ route }: { route: string }) {
  if (route === '/' || route === '') return <Dashboard />
  if (route.startsWith('/browse')) return <Browse route={route} />
  if (route.startsWith('/compare')) return <Compare />
  if (route.startsWith('/position')) return <Explorer route={route} />
  return <p>Not found: {route}</p>
}

export default function App() {
  const route = useHashRoute()

  return (
    <div className="app">
      <nav className="nav">
        <span className="brand">chessdb</span>
        <a href="#/" aria-current={route === '/' || route === '' ? 'page' : undefined}>
          Dashboard
        </a>
        <a
          href="#/browse"
          aria-current={route.startsWith('/browse') ? 'page' : undefined}
        >
          Browse
        </a>
        <a
          href="#/compare"
          aria-current={route.startsWith('/compare') ? 'page' : undefined}
        >
          Compare
        </a>
      </nav>
      <main>
        <Page route={route} />
      </main>
    </div>
  )
}
