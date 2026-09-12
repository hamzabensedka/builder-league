const fs = require('fs')
if (!fs.existsSync('ui/src/ambient/Canvas.jsx')) {
  console.log('canvas UI missing')
  process.exit(1)
}
const src = fs.readFileSync('ui/src/App.jsx', 'utf8')
if (!src.includes('C7')) {
  console.log('C7 tab missing')
  process.exit(1)
}
const canvas = fs.readFileSync('ui/src/ambient/Canvas.jsx', 'utf8')
if (/<input[^>]*type=["']text|<textarea/i.test(canvas)) {
  console.log('chat-style text input in canvas')
  process.exit(1)
}
if (!fs.existsSync('ui/dist/index.html')) {
  console.log('dist not built')
  process.exit(1)
}
console.log('canvas UI present, no chat input, dist built')
