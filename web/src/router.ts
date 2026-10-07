import { useEffect, useState } from 'react'

// Hash router, so static serving needs no rewrites. Routes: '#/', '#/browse',
// '#/position/<id>', '#/position?epd=<enc>'.

function currentHash(): string {
  return window.location.hash.slice(1) || '/'
}

export function useHashRoute(): string {
  const [route, setRoute] = useState(currentHash)

  useEffect(() => {
    const onHashChange = () => setRoute(currentHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  return route
}

export function navigate(path: string): void {
  window.location.hash = path
}
