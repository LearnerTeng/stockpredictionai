export const DEFAULT_API_BASE = `${window.location.protocol}//${window.location.hostname || 'localhost'}:8000`
export const API_BASE = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE

async function parseJson(response, path) {
  try {
    return await response.json()
  } catch {
    throw new Error(`Invalid JSON response from ${path}`)
  }
}

export async function postJson(path, payload) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  const data = await parseJson(response, path)
  if (!response.ok) {
    throw new Error(data.error || `${path} request failed`)
  }

  return data
}
