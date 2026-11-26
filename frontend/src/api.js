export async function get(path) {
  const r = await fetch(`/api${path}`);
  if (!r.ok) throw new Error(await 错误文(r));
  return r.json();
}

export async function post(path, body) {
  const r = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await 错误文(r));
  return r.json();
}

async function 错误文(r) {
  const t = await r.text();
  try {
    const j = JSON.parse(t);
    const d = j.detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object") {
      return d.原因 || d.说明 || `${JSON.stringify(d)}`;
    }
    return t;
  } catch {
    return t || `HTTP ${r.status}`;
  }
}

export async function postFixture(name) {
  const r = await fetch(`/api/装载/夹具?名=${encodeURIComponent(name)}`, { method: "POST" });
  if (!r.ok) throw new Error(await 错误文(r));
  return r.json();
}
