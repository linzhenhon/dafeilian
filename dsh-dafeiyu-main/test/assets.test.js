import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const assetRoot = join(repositoryRoot, 'assets', 'pet')
const manifestPath = join(repositoryRoot, 'assets', 'pet-manifest.json')

async function webpFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) files.push(...await webpFiles(path))
    else if (entry.isFile() && entry.name.endsWith('.webp')) files.push(path)
  }
  return files
}

// libwebp with alpha emits the extended VP8X chunk: canvas size is stored as
// 24-bit little-endian (value - 1) at RIFF payload offsets 24 and 27.
function webpSize(bytes) {
  assert.equal(bytes.subarray(0, 4).toString('ascii'), 'RIFF', 'not a RIFF container')
  assert.equal(bytes.subarray(8, 12).toString('ascii'), 'WEBP', 'not a WebP file')
  assert.equal(bytes.subarray(12, 16).toString('ascii'), 'VP8X', 'expected the extended VP8X chunk')
  return {
    width: bytes.readUIntLE(24, 3) + 1,
    height: bytes.readUIntLE(27, 3) + 1,
  }
}

test('pet manifest allowlists every bundled runtime frame', async () => {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  assert.equal(manifest.formatVersion, 1)
  assert.ok(Object.keys(manifest.clips).length >= 15)

  const declared = new Set()
  for (const [clipName, clip] of Object.entries(manifest.clips)) {
    assert.ok(Array.isArray(clip.frames) && clip.frames.length > 0, `${clipName} has no frames`)
    assert.ok(Number.isInteger(clip.frameMs) && clip.frameMs > 0, `${clipName} has invalid frameMs`)
    for (const frame of clip.frames) {
      assert.equal(typeof frame, 'string')
      const path = resolve(assetRoot, frame)
      assert.ok(path.startsWith(`${assetRoot}${sep}`), `${clipName} escapes the asset root`)
      assert.equal(declared.has(frame), false, `duplicate frame declaration: ${frame}`)
      declared.add(frame)
      const bytes = await readFile(path)
      const { width, height } = webpSize(bytes)
      assert.ok(width > 0 && width <= manifest.maxFrameWidth, `${frame} width exceeds the runtime envelope`)
      assert.ok(height > 0 && height <= manifest.maxFrameHeight, `${frame} height exceeds the runtime envelope`)
    }
  }

  const bundled = new Set((await webpFiles(assetRoot)).map((path) => relative(assetRoot, path).split(sep).join('/')))
  assert.deepEqual([...bundled].sort(), [...declared].sort())
  for (const clip of Object.values(manifest.stateMap)) assert.ok(manifest.clips[clip])
  for (const clip of Object.values(manifest.workingActivityMap)) assert.ok(manifest.clips[clip])
  for (const clip of manifest.idleMicroClips) assert.ok(manifest.clips[clip])
})

test('state clips play full-motion loops at the source-native 24fps cadence', async () => {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  for (const clipName of ['idle', 'waiting', 'thinking', 'working', 'working_search', 'working_command', 'dragging']) {
    const clip = manifest.clips[clipName]
    assert.ok(clip.frames.length >= 30, `${clipName} should import a full-motion sequence`)
    assert.equal(clip.frameMs, 42, `${clipName} should stay on the source-native 24fps cadence`)
    assert.equal(clip.loop, true, `${clipName} state clips must loop`)
    assert.equal(clip.motion, undefined, `${clipName} uses real frames, not procedural motion`)
  }
})

test('touch overlays play once and hand control back to the base state', async () => {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  for (const clipName of ['success', 'error', 'dragging_release', 'head_pat', 'poke', 'tail', 'eat_token', 'idle_stretch', 'idle_yawn']) {
    const clip = manifest.clips[clipName]
    assert.ok(clip, `${clipName} must stay registered for the helper overlays`)
    assert.equal(clip.loop, false, `${clipName} overlays must not loop`)
  }
})

test('source windows preserve entrances and exits, with a separate hanging loop and complete landing', async () => {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  for (const [name, clip] of Object.entries(manifest.clips)) {
    assert.match(clip.source.sha256, /^[a-f0-9]{64}$/, name)
    assert.equal(clip.source.endFrame - clip.source.startFrame, clip.frames.length, name)
    assert.equal(clip.frameMs, 42, name)
    assert.equal(clip.motion, undefined, `${name} must not reuse procedural motion`)
    if (!name.startsWith('dragging')) {
      assert.equal(clip.source.startFrame, 0, `${name} loses its entrance`)
      assert.equal(clip.source.endFrame, clip.source.frameCount, `${name} loses its exit`)
    }
  }
  const hang = manifest.clips.dragging.source
  const landing = manifest.clips.dragging_release.source
  assert.equal(hang.file, landing.file)
  assert.equal(hang.sha256, landing.sha256)
  assert.equal(hang.endFrame, landing.startFrame, 'the hang must stop where the landing begins')
  assert.equal(landing.endFrame, landing.frameCount, 'the landing must return to rest')
  assert.equal(manifest.clips.dragging_dizzy, undefined)
  assert.equal(manifest.clips.dragging_protest, undefined)
  assert.equal(manifest.clips.waiting.source.file, manifest.clips.working_search.source.file)
})

test('idle actions have a full rest interval after playback, in increasing activity order', async () => {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  const { quiet, normal, lively } = manifest.idleMicroIntervalsMs
  assert.ok(quiet[0] >= normal[1] && normal[0] >= lively[1])
  assert.ok(lively[0] >= 12000)
  assert.ok(manifest.idleMicroClips.length >= 2)
  for (const name of manifest.idleMicroClips) assert.equal(manifest.clips[name].loop, false)
})

test('custom voice notifications are valid short mono PCM WAV files', async () => {
  for (const pack of ['original', 'clean', 'video']) {
    for (const name of ['success.wav', 'error.wav', 'approval.wav', 'sleep.wav', 'alarm.wav', 'todo.wav']) {
      const bytes = await readFile(join(repositoryRoot, 'assets', 'sounds', ...(pack === 'original' ? [] : [pack]), name))
      assert.equal(bytes.subarray(0, 4).toString('ascii'), 'RIFF')
      assert.equal(bytes.subarray(8, 12).toString('ascii'), 'WAVE')
      assert.equal(bytes.readUInt16LE(20), 1, `${name} must use PCM encoding`)
      assert.equal(bytes.readUInt16LE(22), 1, `${name} must stay mono`)
      assert.equal(bytes.readUInt32LE(24), 44100, `${name} sample rate drifted`)
      assert.equal(bytes.readUInt16LE(34), 16, `${name} must stay 16-bit`)
      assert.ok(bytes.length > 2 * 44_100 * 2 && bytes.length < 7 * 44_100 * 2 + 4096, `${name} should remain a short spoken alert`)
    }
  }
  for (const name of ['success.wav', 'error.wav', 'approval.wav', 'sleep.wav', 'alarm.wav', 'todo.wav']) {
    const original = await readFile(join(repositoryRoot, 'assets', 'sounds', name))
    const clean = await readFile(join(repositoryRoot, 'assets', 'sounds', 'clean', name))
    assert.equal(original.equals(clean), false, `${name} should contain two distinct recordings`)
  }
})

test('custom character has expressive transparent poses for each main state', async () => {
  const manifest = JSON.parse(await readFile(join(repositoryRoot, 'assets', 'pet-manifest-custom.json'), 'utf8'))
  assert.equal(manifest.characterId, 'public-robot')
  assert.equal(manifest.clips.idle.frames[0], 'custom/idle_pose.png')
  assert.equal(manifest.clips.thinking.frames[0], 'custom/thinking_pose.png')
  assert.equal(manifest.clips.working.frames[0], 'custom/working_pose.png')
  assert.equal(manifest.clips.waiting.frames[0], 'custom/waiting_pose.png')
  assert.equal(manifest.clips.dragging.frames[0], 'custom/flying.png')
  assert.equal(manifest.clips.dragging_up.frames[0], 'custom/flying_back.png')
  assert.equal(manifest.clips.dragging_side.frames[0], 'custom/flying_side.png')
  assert.equal(manifest.clips.voice_recording.frames[0], 'custom/recording_pose.png')
  assert.equal(manifest.clips.voice_calling.frames[0], 'custom/calling_pose.png')
  assert.equal(manifest.clips.file_hover.frames[0], 'custom/file_ready.png')
  assert.deepEqual(manifest.clips.file_catch.frames, ['custom/file_ready.png', 'custom/file_caught.png', 'custom/file_caught.png'])
  for (const action of ['head_pat', 'poke', 'tail']) {
    assert.equal(manifest.clips[action].frames[0], `custom/${action}.png`)
    assert.ok(manifest.clips[action].frameMs >= 700, `${action} needs a visible reaction`)
  }
  assert.ok(Math.min(...manifest.motionProfiles.dragging.keys.map((key) => key[2])) <= -20)
  assert.deepEqual(manifest.idleMicroClips, ['idle_stretch', 'idle_yawn'])
  for (const [name, clip] of Object.entries(manifest.clips)) {
    const profile = manifest.motionProfiles[name]
    assert.ok(profile, `${name} needs a motion profile`)
    assert.ok(profile.periodMs > 0 && profile.keys.length >= 2)
    assert.equal(profile.keys[0][0], 0)
    assert.equal(profile.keys.at(-1)[0], profile.periodMs)
    assert.equal(profile.loop, clip.loop)
    for (const key of profile.keys) assert.equal(key.length, 6)
  }
  for (const view of ['front', 'side', 'back', 'flying', 'idle_pose', 'thinking_pose', 'working_pose', 'waiting_pose']) {
    const bytes = await readFile(join(assetRoot, 'custom', `${view}.png`))
    assert.equal(bytes.subarray(1, 4).toString('ascii'), 'PNG')
    assert.equal(bytes.readUInt32BE(16), manifest.maxFrameWidth)
    assert.equal(bytes.readUInt32BE(20), manifest.maxFrameHeight)
    assert.equal(bytes[25], 6, `${view} must use RGBA pixels`)
  }
  for (const view of ['flying_side', 'flying_back', 'head_pat', 'poke', 'tail', 'recording_pose', 'calling_pose', 'file_ready', 'file_caught']) {
    const bytes = await readFile(join(assetRoot, 'custom', `${view}.png`))
    assert.equal(bytes.subarray(1, 4).toString('ascii'), 'PNG')
    const width = bytes.readUInt32BE(16)
    const height = bytes.readUInt32BE(20)
    assert.ok(width >= manifest.maxFrameWidth && height >= manifest.maxFrameHeight)
    assert.ok(Math.abs(width / height - manifest.maxFrameWidth / manifest.maxFrameHeight) < 0.02)
    assert.equal(bytes[25], 6, `${view} must use RGBA pixels`)
  }
  for (const [name, clip] of Object.entries(manifest.clips)) {
    assert.equal(clip.frames.length, name === 'file_catch' ? 3 : 1)
    for (const frame of clip.frames) {
      assert.match(frame, /^custom\/(front|side|back|flying|flying_side|flying_back|head_pat|poke|tail|idle_pose|thinking_pose|working_pose|waiting_pose|recording_pose|calling_pose|file_ready|file_caught)\.png$/)
    }
  }
})
