import { appendFileSync, writeFileSync } from 'node:fs'
import { createInterface } from 'node:readline'

const [logPath, readyPath] = process.argv.slice(2)
process.stdout.write(`${JSON.stringify({ protocolVersion: 1, kind: 'ready' })}\n`)
let announced = false
createInterface({ input: process.stdin }).on('line', (line) => {
  const message = JSON.parse(line)
  appendFileSync(logPath, `${line}\n`)
  if (!announced && message.kind !== 'shutdown') {
    announced = true
    process.stdout.write(`${JSON.stringify({ protocolVersion: 1, kind: 'voice_mode', active: true })}\n`)
    writeFileSync(readyPath, 'ready')
  }
  if (message.kind === 'shutdown') process.exit(0)
})
