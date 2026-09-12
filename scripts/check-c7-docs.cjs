const fs = require('fs')
const files = ['docs/architecture-c7.md', 'docs/thesis-c7.md', 'demo/script-c7.md']
const missing = files.filter((f) => !fs.existsSync(f))
if (missing.length) {
  console.log('MISSING: ' + missing.join(' | '))
  process.exit(1)
}
const t = fs
  .readFileSync('docs/thesis-c7.md', 'utf8')
  .replace(/^#.*$/m, '')
  .replace(/[#*`>|]/g, '')
  .split(/\s+/)
  .filter(Boolean).length
if (t > 320) {
  console.log('thesis too long: ' + t)
  process.exit(1)
}
console.log('c7 docs complete, thesis ' + t + ' words')
