// Thin wrapper around the REST API.
async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && data.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => `${d.loc.slice(-1)[0]}: ${d.msg}`).join("; ")
      : detail || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

export const api = {
  health: () => request("/api/health"),
  stats: () => request("/api/stats"),
  list: ({ q = "", language = "", limit = 10, offset = 0 } = {}) => {
    const params = new URLSearchParams({ limit, offset });
    if (q) params.set("q", q);
    if (language) params.set("language", language);
    return request(`/api/transcriptions?${params}`);
  },
  get: (id) => request(`/api/transcriptions/${id}`),
  create: (data) => request("/api/transcriptions", { method: "POST", body: data }),
  update: (id, data) => request(`/api/transcriptions/${id}`, { method: "PATCH", body: data }),
  remove: (id) => request(`/api/transcriptions/${id}`, { method: "DELETE" }),
};
