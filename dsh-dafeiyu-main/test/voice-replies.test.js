import assert from 'node:assert/strict'
import test from 'node:test'
import { displayReply, spokenReply } from '../src/voice-replies.js'

test('call mode speaks only final assistant prose', () => {
  assert.equal(spokenReply({ data: { message: { role: 'assistant', channel: 'analysis', content: 'hidden' } } }), '')
  assert.equal(spokenReply({ data: { message: { role: 'user', content: 'hello' } } }), '')
  assert.equal(spokenReply({ data: { message: { role: 'assistant', channel: 'final', content: [
    { type: 'text', text: '任务完成。' }, { type: 'tool_call', text: 'internal' },
  ] } } }), '任务完成。')
  assert.equal(spokenReply({ data: { message: { role: 'assistant', content: '请看[说明](https://example.com)。' } } }), '请看说明。')
})

test('call transcript keeps final answer content that speech abbreviates', () => {
  const event = { data: { message: { role: 'assistant', channel: 'final', content: '请看[说明](https://example.com)。\n```js\nconst answer = 42\n```' } } }
  assert.equal(displayReply(event), '请看[说明](https://example.com)。\n```js\nconst answer = 42\n```')
  assert.equal(spokenReply(event), '请看说明。 代码内容请查看对话。')
})
