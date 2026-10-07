import { useEffect, useState } from 'react'
import { apiGet, ApiError } from './api'

interface ApiState<T> {
  data: T | null
  loading: boolean
  error: ApiError | Error | null
}

// Refetches when `path` changes and aborts the stale request first.
// `path === null` means "don't fetch yet".
export function useApi<T>(path: string | null): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: path !== null,
    error: null,
  })

  useEffect(() => {
    if (path === null) {
      setState({ data: null, loading: false, error: null })
      return
    }
    const controller = new AbortController()
    setState({ data: null, loading: true, error: null })
    apiGet<T>(path, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, loading: false, error: null })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            data: null,
            loading: false,
            error: error instanceof Error ? error : new Error(String(error)),
          })
        }
      })
    return () => controller.abort()
  }, [path])

  return state
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}
