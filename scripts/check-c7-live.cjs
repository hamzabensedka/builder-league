const BASE = 'https://builder-league-trust.onrender.com'
fetch(BASE + '/health')
  .then((r) => r.json())
  .then((j) => {
    console.log(JSON.stringify(j))
    process.exit(j.status === 'ok' ? 0 : 1)
  })
  .catch((e) => {
    console.log('ERR ' + e.message)
    process.exit(1)
  })
