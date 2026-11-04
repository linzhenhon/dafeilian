import { writeFileSync } from 'node:fs'
import { createInterface } from 'node:readline'

process.stdout.write(`${JSON.stringify({ protocolVersion: 1, kind: 'ready' })}\n`)

let submitted = false
createInterface({ input: process.stdin }).on('line', (line) => {
  const message = JSON.parse(line)
  if (message.kind === 'hello' && !submitted) {
    submitted = true
    setTimeout(() => process.stdout.write(`${JSON.stringify({
      protocolVersion: 1, kind: 'submit_task', requestId: 'fixture-task-1', text: '从桌宠输入的任务',
    })}\n`), 100)
  }
  if (message.kind === 'task_result') writeFileSync(process.argv[2], JSON.stringify(message))
  if (message.kind === 'shutdown') process.exit(0)
})
