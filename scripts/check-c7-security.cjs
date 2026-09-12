const fs = require('fs')
const walk = (d) =>
  fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(d + '/' + e.name) : [d + '/' + e.name])
const src = walk('core/ambientcore')
  .filter((f) => f.endsWith('.py'))
  .map((f) => fs.readFileSync(f, 'utf8'))
  .join('\n')
if (/\beval\(|\bexec\(/.test(src)) {
  console.log('eval/exec found')
  process.exit(1)
}
const domApp = walk('core/ambientcore')
  .filter((f) => f.endsWith('.py') && !f.includes('adapters'))
  .map((f) => fs.readFileSync(f, 'utf8'))
  .join('\n')
if (/openai|anthropic|langchain|litellm|httpx/i.test(domApp)) {
  console.log('LLM/httpx reference on inference path')
  process.exit(1)
}
console.log('ambientcore security sweep clean')
