async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
}

export function wsUrl(taskId: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/ws/tasks/${taskId}`
}

export function fileDownloadUrl(dir: string, file: string): string {
  return `/api/files/download?dir=${encodeURIComponent(dir)}&file=${encodeURIComponent(file)}`
}

export function fileStreamUrl(dir: string, file: string): string {
  return `/api/files/stream?dir=${encodeURIComponent(dir)}&file=${encodeURIComponent(file)}`
}
