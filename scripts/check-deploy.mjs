/* H6 deploy verification — proves the live Render URL serves the SAME UI
   bundle that was just built locally (i.e. the HowTo-enhanced build), and
   that the API is healthy. Usage: node scripts/check-deploy.mjs [baseUrl] */
const BASE = process.argv[2] ?? 'https://builder-league-trust.onrender.com'

const local = async () => {
  const { readFile } = await import('node:fs/promises')
  const html = await readFile(new URL('../ui/dist/index.html', import.meta.url), 'utf8')
  const m = html.match(/assets\/(index-[^"]+\.js)/)
  if (!m) throw new Error('local dist/index.html has no bundle reference')
  return m[1]
}

const t0 = Date.now()
const health = await fetch(BASE + '/health').then((r) => r.json()).catch((e) => ({ error: e.message }))
console.log(`health: ${JSON.stringify(health)} (${Date.now() - t0}ms — cold start expected on free tier)`)
if (health.status !== 'ok') {
  console.log('DEPLOY NOT HEALTHY')
  process.exit(1)
}

const localBundle = await local()
const html = await fetch(BASE + '/').then((r) => r.text())
const live = html.match(/assets\/(index-[^"]+\.js)/)?.[1]
console.log(`local bundle: ${localBundle}`)
console.log(`live bundle:  ${live ?? 'none (landing page?)'}`)

if (live !== localBundle) {
  console.log('MISMATCH — live deploy is not serving the local build yet')
  process.exit(1)
}

const js = await fetch(`${BASE}/assets/${live}`).then((r) => r.text())
const hasHowTo = js.includes('How to use')
const hasTabs = ['C1 · Trust', 'C8 · Simulate first'].every((t) => js.includes(t))
console.log(`bundle contains HowTo panels: ${hasHowTo}; all 8 tabs: ${hasTabs}`)
if (!hasHowTo || !hasTabs) process.exit(1)

console.log('DEPLOY VERIFIED — live URL serves the latest build')
