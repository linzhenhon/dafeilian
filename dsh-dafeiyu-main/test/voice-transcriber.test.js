import assert from 'node:assert/strict'
import { join } from 'node:path'
import test from 'node:test'
import { isValidRecordingPath } from '../src/voice-transcriber.js'

test('recording path is accepted only from the shared voice directory', () => {
  const directory = join(process.cwd(), '.build', 'test-temp', 'voice')
  const name = `${'a'.repeat(32)}.wav`
  assert.equal(isValidRecordingPath(join(directory, name), directory), true)
  assert.equal(isValidRecordingPath(join(directory, '..', name), directory), false)
  assert.equal(isValidRecordingPath(join(directory, 'other.wav'), directory), false)
  assert.equal(isValidRecordingPath(join(directory, '..', 'voice-fake', name), directory), false)
})
