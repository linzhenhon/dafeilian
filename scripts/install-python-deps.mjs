import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const requirements = resolve(packageRoot, 'requirements.txt')
const bundledHelpers = {
  'win32-x64': 'runtime/bin/win32-x64/dsh-dafeiyu-helper.exe',
  'win32-arm64': 'runtime/bin/win32-arm64/dsh-dafeiyu-helper.exe',
  'linux-x64': 'runtime/bin/linux-x64/dsh-dafeiyu-helper',
  'linux-arm64': 'runtime/bin/linux-arm64/dsh-dafeiyu-helper',
  darwin: 'runtime/bin/darwin/dsh-dafeiyu-helper.app/Contents/MacOS/dsh-dafeiyu-helper',
}
const platformKey = process.platform === 'darwin'
  ? 'darwin'
  : `${process.platform}-${process.arch}`
const bundledHelper = bundledHelpers[platformKey]

if (bundledHelper && existsSync(resolve(packageRoot, bundledHelper))) {
  console.log(`dsh-dafeilian: bundled Helper found for ${platformKey}; skipping Python dependency setup.`)
  process.exit(0)
}

if (process.env.DSH_DAFEILIAN_SKIP_PYTHON_DEPS === '1') {
  console.log('dsh-dafeilian: skipped automatic Python dependency setup (DSH_DAFEILIAN_SKIP_PYTHON_DEPS=1).')
  process.exit(0)
}

const pipArgs = ['-m', 'pip', 'install', '--user', '-r', requirements]
const candidates = process.platform === 'win32'
  ? [{ command: 'py', args: ['-3', ...pipArgs] }, { command: 'python', args: pipArgs }]
  : [{ command: 'python3', args: pipArgs }, { command: 'python', args: pipArgs }]

for (const candidate of candidates) {
  const result = spawnSync(candidate.command, candidate.args, { stdio: 'inherit', windowsHide: true })
  if (result.error?.code === 'ENOENT') continue
  if (result.error) {
    console.error(`dsh-dafeilian: failed to run ${candidate.command}: ${result.error.message}`)
    process.exit(1)
  }
  if (result.status === 0) {
    console.log('dsh-dafeilian: Python Helper dependencies installed. Restart DSH Desktop if it is already open.')
    process.exit(0)
  }
  if (result.status !== 9009) {
    console.error('dsh-dafeilian: Python dependency installation failed. Install the requirements manually or set DSH_DAFEILIAN_SKIP_PYTHON_DEPS=1 to continue without the visual Helper.')
    process.exit(result.status ?? 1)
  }
}

console.error('dsh-dafeilian: no Python 3 installation was found. Install Python 3 and pip, then reinstall the plugin. The Python fallback requires PySide6.')
process.exit(1)
