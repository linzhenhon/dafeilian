window.__ModuleLoader__.load({ id: 'dsh-dafeilian', factory: (require) => {
  const module = { exports: {} }
  const exports = module.exports
  const React = require('react')
  const { useEffect, useRef, useState } = React
  const CONFIG_ENDPOINT = '/plugins/dsh-dafeiyu/config'
  const EVENTS_ENDPOINT = '/plugins/dsh-dafeiyu/events'
  const MANIFEST_ENDPOINT = '/plugins/dsh-dafeiyu/manifest'
  const FRAME_ENDPOINT = '/plugins/dsh-dafeiyu/frame'
  const SOUND_ENDPOINT = '/plugins/dsh-dafeiyu/sound'
  const CUSTOM_SOUND_ENDPOINT = '/plugins/dsh-dafeiyu/custom-sounds'
  const BALANCE_ENDPOINT = '/plugins/dsh-dafeiyu/balance'
  const TASK_TARGET_ENDPOINT = '/plugins/dsh-dafeiyu/task-target'

  const cardStyle = {
    listStyle: 'none', border: '1px solid var(--border-color, #d8d8d8)', borderRadius: 12,
    padding: 16, background: 'var(--surface-color, transparent)', display: 'grid', gap: 14,
  }
  const rowStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 20 }
  const selectStyle = { minWidth: 120, padding: '6px 10px', borderRadius: 8 }
  const BUBBLE_STATE_OPTIONS = [
    ['IDLE', '空闲'],
    ['THINKING', '思考中'],
    ['WORKING', '工作中'],
    ['WAITING', '等待确认'],
    ['SUCCESS', '完成'],
    ['ERROR', '错误'],
  ]
  const SOUND_STATE_OPTIONS = [
    ['SUCCESS', '对话完成'],
    ['ERROR', '工具出错'],
    ['APPROVAL', '等待审批'],
  ]
  const REMINDER_SOUND_OPTIONS = [
    ['SLEEP', '该睡觉了'],
    ['ALARM', '定的闹钟'],
    ['TODO', '还有待办任务'],
  ]
  const SOUND_PACK_OPTIONS = [
    ['video', '提示音 C'],
    ['clean', '提示音 B'],
    ['original', '提示音 A'],
    ['custom', '自定义'],
  ]
  const bubbleGridStyle = {
    display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: '6px 14px',
    padding: '10px 12px', border: '1px solid var(--border-color, #d8d8d8)', borderRadius: 8,
  }
  const MARKET_INTERVAL_OPTIONS = [
    ['1m', '1 分钟'], ['15m', '15 分钟'], ['1h', '1 小时'], ['4h', '4 小时'],
  ]

  function marketSymbols(value) {
    const symbols = [...new Set(String(value ?? '').split(',').map((item) => item.trim().toUpperCase())
      .filter((item) => /^[A-Z0-9]{5,20}$/.test(item)))].slice(0, 5)
    return symbols.length ? symbols : ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT']
  }

  function Field({ label, hint, children }) {
    return React.createElement('label', { style: rowStyle },
      React.createElement('span', null,
        React.createElement('span', { style: { display: 'block', fontWeight: 600 } }, label),
        React.createElement('small', { style: { display: 'block', opacity: 0.65, marginTop: 3 } }, hint),
      ),
      children,
    )
  }

  function IdleTitleEditor({ value, disabled, onSave }) {
    const [draft, setDraft] = useState(value)
    useEffect(() => setDraft(value), [value])
    const title = draft.trim()
    const save = () => {
      if (!disabled && title && title !== value) onSave(title)
    }
    return React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
      React.createElement('input', {
        type: 'text', value: draft, maxLength: 40, disabled,
        'aria-label': '待机文案', placeholder: '小弟陪大哥待命',
        style: { minWidth: 0, width: 220, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border-color, #d8d8d8)' },
        onChange: (event) => setDraft(event.target.value),
        onKeyDown: (event) => { if (event.key === 'Enter') save() },
      }),
      React.createElement('button', { type: 'button', disabled: disabled || !title || title === value, onClick: save }, '保存'),
    )
  }

  function PathEditor({ value, disabled, placeholder, onSave }) {
    const [draft, setDraft] = useState(value)
    useEffect(() => setDraft(value), [value])
    const save = () => { if (!disabled && draft !== value) onSave(draft.trim()) }
    return React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
      React.createElement('input', {
        type: 'text', value: draft, maxLength: 1024, disabled, placeholder,
        style: { minWidth: 0, width: 320, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border-color, #d8d8d8)' },
        onChange: (event) => setDraft(event.target.value),
        onKeyDown: (event) => { if (event.key === 'Enter') save() },
      }),
      React.createElement('button', { type: 'button', disabled: disabled || draft === value, onClick: save }, '保存'),
    )
  }

  function BubbleStatePicker({ value, disabled, onChange, options = BUBBLE_STATE_OPTIONS }) {
    const selected = Array.isArray(value) ? value : []
    const toggle = (state, checked) => {
      const next = new Set(selected)
      if (checked) next.add(state)
      else next.delete(state)
      onChange([...next])
    }
    return React.createElement('div', { style: bubbleGridStyle },
      ...options.map(([state, label]) =>
        React.createElement('label', { key: state, style: { display: 'flex', alignItems: 'center', gap: 4 } },
          React.createElement('input', {
            type: 'checkbox', checked: selected.includes(state), disabled,
            onChange: (event) => toggle(state, event.target.checked),
          }),
          label,
        ),
      ),
    )
  }

  function BalancePanel({ enabled, source }) {
    const [snapshot, setSnapshot] = useState(null)
    const [busy, setBusy] = useState(false)
    const sequence = useRef(0)
    const request = async (force = false) => {
      const current = ++sequence.current
      setBusy(true)
      try {
        const response = await fetch(BALANCE_ENDPOINT, { method: force ? 'POST' : 'GET', cache: 'no-store' })
        if (!response.ok) throw new Error('balance request failed')
        const next = await response.json()
        if (current === sequence.current) setSnapshot(next)
      } catch {
        if (current === sequence.current) setSnapshot((previous) => ({ ...previous, status: 'error', error: '余额查询暂时不可用，请稍后刷新。' }))
      } finally {
        if (current === sequence.current) setBusy(false)
      }
    }
    useEffect(() => {
      setSnapshot(null)
      if (!enabled) return
      void request()
      const timer = setInterval(() => void request(), 60000)
      let stream
      try {
        stream = new EventSource(EVENTS_ENDPOINT)
        stream.onmessage = (event) => {
          try {
            const next = JSON.parse(event.data)
            if (next.kind !== 'balance') return
            sequence.current += 1
            setSnapshot(next)
            setBusy(false)
          } catch {}
        }
      } catch {}
      return () => { clearInterval(timer); stream?.close(); sequence.current += 1 }
    }, [enabled, source])
    if (!enabled) return null
    const money = (row, field) => new Intl.NumberFormat('zh-CN', {
      style: 'currency', currency: row.currency, minimumFractionDigits: 2, maximumFractionDigits: 4,
    }).format(row[field])
    return React.createElement('section', { 'aria-label': 'DeepSeek 余额', 'data-testid': 'dsh-dafeilian-balance', style: { borderTop: '1px solid var(--border-color, #d8d8d8)', paddingTop: 14 } },
      React.createElement('div', { style: rowStyle },
        React.createElement('strong', null, 'DeepSeek 余额'),
        React.createElement('button', { type: 'button', disabled: busy, onClick: () => void request(true) }, busy ? '查询中…' : '刷新余额'),
      ),
      snapshot?.source ? React.createElement('small', null, snapshot.source === 'account' ? '已登录的 DeepSeek 账户' : 'DSH 模型设置中的 API Key') : null,
      snapshot?.balances?.length ? React.createElement('table', { style: { width: '100%', textAlign: 'left', marginTop: 10 } },
        React.createElement('thead', null, React.createElement('tr', null,
          ...['币种', '总余额', '赠送', '充值'].map((label) => React.createElement('th', { key: label, scope: 'col' }, label)),
        )),
        React.createElement('tbody', null, ...snapshot.balances.map((row) => React.createElement('tr', { key: row.currency },
          React.createElement('th', { scope: 'row' }, row.currency),
          ...['total', 'granted', 'toppedUp'].map((field) => React.createElement('td', { key: field }, money(row, field))),
        ))),
      ) : null,
      snapshot?.error ? React.createElement('p', { role: 'status' }, snapshot.error) : null,
      snapshot?.available === false ? React.createElement('p', { role: 'status' }, '账户当前没有可用余额。') : null,
      snapshot?.checkedAt ? React.createElement('small', null,
        `${snapshot.status === 'error' ? '上次成功查询' : '更新时间'}：${new Date(snapshot.checkedAt).toLocaleTimeString()} · 每分钟自动刷新`,
      ) : !snapshot?.error ? React.createElement('p', { role: 'status' }, '正在查询余额…') : null,
    )
  }

  function SoundPackPicker({ value, disabled, onChange }) {
    const soundRows = (pack, label, options) => React.createElement('div', { style: { display: 'grid', gap: 6, marginTop: 8 } },
      ...options.map(([state, stateLabel]) => React.createElement('div', {
        key: state, style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
      },
      React.createElement('span', { style: { minWidth: 65 } }, stateLabel),
      React.createElement('audio', {
        controls: true, preload: 'none', 'aria-label': `${label}：${stateLabel}`,
        src: `${SOUND_ENDPOINT}?pack=${pack}&state=${state}`,
        style: { width: 'min(100%, 280px)', height: 32 },
      }))))
    return React.createElement('fieldset', { style: { border: '1px solid var(--border-color, #d8d8d8)', borderRadius: 8, padding: '10px 12px', margin: 0 } },
      React.createElement('legend', { style: { fontWeight: 600 } }, '提示音版本'),
      React.createElement('small', { style: { display: 'block', opacity: 0.7, marginBottom: 8 } }, '公开版提供三套合成提示音；可试听各场景，也可上传经授权的自定义音频。生活提醒时间稍后设置。'),
      ...SOUND_PACK_OPTIONS.map(([pack, label]) => React.createElement('div', {
        key: pack,
        style: { border: '1px solid var(--border-color, #d8d8d8)', borderRadius: 8, padding: 10, marginBottom: 8 },
      },
      React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 } },
        React.createElement('input', {
          type: 'radio', name: 'dsh-dafeilian-sound-pack', value: pack,
          checked: value === pack, disabled,
          onChange: () => void onChange(pack),
        }),
        label,
      ),
      pack === 'custom' ? React.createElement('small', { style: { display: 'block', marginTop: 8, opacity: 0.7 } }, '在下方分别上传六种场景的音频；未上传时沿用提示音 A。') : soundRows(pack, label, SOUND_STATE_OPTIONS),
      pack === 'custom' ? null : React.createElement('details', { style: { marginTop: 10 } },
        React.createElement('summary', { style: { cursor: 'pointer' } }, '生活提醒提示音（3 种）'),
        soundRows(pack, label, REMINDER_SOUND_OPTIONS),
      ),
      )),
    )
  }

  async function prepareCustomWav(file) {
    if (file.size > 20 * 1024 * 1024) throw new Error('源音频不能超过 20 MB')
    const AudioContextClass = window.AudioContext || window.webkitAudioContext
    if (!AudioContextClass || !window.OfflineAudioContext) throw new Error('当前页面不支持音频转换')
    const decoder = new AudioContextClass()
    let decoded
    try {
      decoded = await decoder.decodeAudioData(await file.arrayBuffer())
    } catch {
      throw new Error('无法读取此音频，请换用 WAV、MP3 或 M4A 文件')
    } finally {
      await decoder.close().catch(() => {})
    }
    if (decoded.duration < 0.2 || decoded.duration > 30) throw new Error('提醒音频长度需为 0.2 至 30 秒')
    const sampleRate = 44100
    const context = new window.OfflineAudioContext(1, Math.round(decoded.duration * sampleRate), sampleRate)
    const source = context.createBufferSource()
    source.buffer = decoded
    source.connect(context.destination)
    source.start(0)
    const rendered = await context.startRendering()
    const samples = rendered.getChannelData(0)
    const bytes = new ArrayBuffer(44 + samples.length * 2)
    const view = new DataView(bytes)
    const ascii = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)) }
    ascii(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); ascii(8, 'WAVE')
    ascii(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true)
    view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true)
    view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true)
    view.setUint16(34, 16, true); ascii(36, 'data'); view.setUint32(40, samples.length * 2, true)
    for (let i = 0; i < samples.length; i++) {
      const sample = Math.max(-1, Math.min(1, samples[i]))
      view.setInt16(44 + i * 2, sample < 0 ? Math.round(sample * 32768) : Math.round(sample * 32767), true)
    }
    return bytes
  }

  function CustomSoundPicker({ disabled }) {
    const [states, setStates] = useState({})
    const [busyState, setBusyState] = useState(null)
    const [error, setError] = useState('')
    const [version, setVersion] = useState(0)
    useEffect(() => {
      let active = true
      fetch(CUSTOM_SOUND_ENDPOINT, { cache: 'no-store' })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error('无法读取自定义音频')))
        .then((result) => { if (active) setStates(result.states ?? {}) })
        .catch(() => { if (active) setError('无法读取自定义音频') })
      return () => { active = false }
    }, [])
    const change = async (state, file) => {
      if (!file) return
      setBusyState(state); setError('')
      try {
        const wav = await prepareCustomWav(file)
        const response = await fetch(`${CUSTOM_SOUND_ENDPOINT}?state=${state}`, {
          method: 'POST', headers: { 'content-type': 'audio/wav' }, body: wav,
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.error || '上传失败')
        setStates((previous) => ({ ...previous, [state]: true }))
        setVersion(Date.now())
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : '上传失败')
      } finally { setBusyState(null) }
    }
    const remove = async (state) => {
      setBusyState(state); setError('')
      try {
        const response = await fetch(`${CUSTOM_SOUND_ENDPOINT}?state=${state}`, { method: 'DELETE' })
        const result = await response.json()
        if (!response.ok) throw new Error(result.error || '恢复原版失败')
        setStates((previous) => ({ ...previous, [state]: false }))
        setVersion(Date.now())
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : '恢复原版失败')
      } finally { setBusyState(null) }
    }
    return React.createElement('section', { style: { border: '1px solid var(--border-color, #d8d8d8)', borderRadius: 8, padding: 12 } },
      React.createElement('strong', null, '自定义提醒音频'),
      React.createElement('small', { style: { display: 'block', margin: '5px 0 10px', opacity: 0.7 } }, '每种场景可单独上传 WAV、MP3 或 M4A（最长 30 秒）。文件保存在本机；未上传的场景播放提示音 A。睡觉、闹钟和待办目前只提供试听。'),
      ...[...SOUND_STATE_OPTIONS, ...REMINDER_SOUND_OPTIONS].map(([state, label]) => React.createElement('div', {
        key: state, style: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginTop: 8 },
      },
      React.createElement('span', { style: { minWidth: 90 } }, label),
      React.createElement('input', { type: 'file', accept: 'audio/*,.wav,.mp3,.m4a',
        'aria-label': `上传${label}音频`, disabled: disabled || Boolean(busyState),
        style: { maxWidth: 200 },
        onChange: (event) => { const file = event.target.files?.[0]; event.target.value = ''; void change(state, file) },
      }),
      React.createElement('audio', { controls: true, preload: 'none', 'aria-label': `自定义：${label}`,
        src: `${SOUND_ENDPOINT}?pack=custom&state=${state}&v=${version}`, style: { width: 'min(100%, 220px)', height: 32 },
      }),
      React.createElement('small', { style: { opacity: 0.7 } }, busyState === state ? '处理中…' : states[state] ? '已上传' : '沿用原版'),
      states[state] ? React.createElement('button', { type: 'button', disabled: disabled || Boolean(busyState),
        onClick: () => void remove(state) }, '恢复原版') : null,
      )),
      error ? React.createElement('p', { role: 'alert', style: { color: '#c62828' } }, error) : null,
    )
  }

  function BigFishCard({ view } = {}) {
    const [status, setStatus] = useState('loading')
    const [value, setValue] = useState({})
    const [busy, setBusy] = useState(false)
    const patchSeq = useRef(0)
    const sliderTimers = useRef(new Map())
    const writable = status === 'ready' && !busy
    useEffect(() => {
      let active = true
      fetch(CONFIG_ENDPOINT, { cache: 'no-store' })
        .then(async (response) => {
          if (!response.ok) throw new Error(`settings request failed: ${response.status}`)
          return response.json()
        })
        .then((next) => { if (active) { setValue(next); setStatus('ready') } })
        .catch(() => { if (active) setStatus('unavailable') })
      return () => {
        active = false
        for (const timer of sliderTimers.current.values()) clearTimeout(timer)
        sliderTimers.current.clear()
      }
    }, [])
    const write = async (field, next) => {
      const seq = ++patchSeq.current
      setBusy(true)
      try {
        const response = await fetch(CONFIG_ENDPOINT, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ [field]: next }),
        })
        if (!response.ok) throw new Error(`settings write failed: ${response.status}`)
        const updated = await response.json()
        if (seq === patchSeq.current) {
          setValue(updated)
          setStatus('ready')
        }
      } catch {
        if (seq === patchSeq.current) setStatus('unavailable')
      } finally {
        if (seq === patchSeq.current) setBusy(false)
      }
    }
    const writeSlider = (field, next) => {
      // Keep the slider responsive while dragging: update the local value
      // immediately and send a single debounced PATCH once the user pauses.
      setValue((prev) => ({ ...prev, [field]: next }))
      // Invalidate any in-flight write so a stale response cannot overwrite
      // the optimistic slider value while the user keeps dragging.
      patchSeq.current += 1
      const pending = sliderTimers.current.get(field)
      if (pending) clearTimeout(pending)
      const timer = setTimeout(() => {
        sliderTimers.current.delete(field)
        void write(field, next)
      }, 250)
      sliderTimers.current.set(field, timer)
    }
    const watchSymbols = marketSymbols(value.marketWatchSymbols)
    const watchSymbol = watchSymbols.includes(value.marketWatchSymbol) ? value.marketWatchSymbol : watchSymbols[0]
    return React.createElement(view === 'page' ? 'section' : 'li', { style: cardStyle, 'data-testid': 'dsh-dafeilian-settings' },
      React.createElement('div', null,
        React.createElement('strong', { style: { fontSize: 16 } }, '大肥鱼桌面伴侣'),
        React.createElement('p', { style: { margin: '5px 0 0', opacity: 0.72 } }, '跟随 DSH WebUI 或桌面端启动，在桌面上显示任务状态和余额。'),
      ),
      status === 'unavailable'
        ? React.createElement('span', { role: 'status' }, '大肥鱼设置尚未连接到 DSH Host。')
        : status === 'loading'
        ? React.createElement('span', null, '正在读取设置…')
        : React.createElement(React.Fragment, null,
          React.createElement(Field, { label: '启用大肥鱼', hint: '关闭后立即退出；重新开启无需单独启动程序。' },
            React.createElement('input', {
              type: 'checkbox', checked: value.enabled !== false, disabled: !writable,
              onChange: (event) => void write('enabled', event.target.checked),
            }),
          ),
          React.createElement('div', { style: { borderTop: '1px solid var(--border-color, #d8d8d8)', paddingTop: 14, display: 'grid', gap: 12 } },
            React.createElement('strong', null, '炒币盯盘动作'),
            React.createElement(Field, { label: '启用实时盯盘', hint: '通过币安公开现货行情查看涨跌，无需登录或 API Key。' },
              React.createElement('input', { type: 'checkbox', checked: value.marketWatchEnabled === true, disabled: !writable,
                onChange: (event) => void write('marketWatchEnabled', event.target.checked) }),
            ),
            React.createElement(Field, { label: '监控币种（最多 5 个）', hint: '输入币安 USDT 现货交易对，用英文逗号分隔；默认 BTC、ETH、SOL、BNB、DOGE。' },
              React.createElement(PathEditor, { value: value.marketWatchSymbols ?? 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,DOGEUSDT', disabled: !writable,
                placeholder: 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,DOGEUSDT', onSave: (next) => void write('marketWatchSymbols', next) }),
            ),
            React.createElement(Field, { label: '桌宠展示币种', hint: '最多同时监控五个，只在桌宠行情卡片展示一个。' },
              React.createElement('select', { value: watchSymbol, disabled: !writable, style: selectStyle,
                onChange: (event) => void write('marketWatchSymbol', event.target.value) },
                ...watchSymbols.map((symbol) => React.createElement('option', { key: symbol, value: symbol }, symbol.replace(/USDT$/, '/USDT')))),
            ),
            React.createElement(Field, { label: '涨跌周期', hint: '显示当前 K 线相对开盘价的实时变化。' },
              React.createElement('select', { value: value.marketWatchInterval ?? '15m', disabled: !writable, style: selectStyle,
                onChange: (event) => void write('marketWatchInterval', event.target.value) },
                ...MARKET_INTERVAL_OPTIONS.map(([interval, label]) => React.createElement('option', { key: interval, value: interval }, label))),
            ),
          ),
          React.createElement(Field, { label: '角色大小', hint: `${Math.round((value.scale ?? 1) * 100)}%` },
            React.createElement('input', {
              type: 'range', min: 0.55, max: 1.4, step: 0.05, value: value.scale ?? 1,
              disabled: status !== 'ready',
              onChange: (event) => void writeSlider('scale', Number(event.target.value)),
            }),
          ),
          React.createElement(Field, { label: '活跃程度', hint: '待机动作结束后休息：安静 45～90 秒、标准 25～45 秒、活泼 12～22 秒。' },
            React.createElement('select', {
              value: value.activityLevel ?? 'normal', disabled: !writable, style: selectStyle,
              onChange: (event) => void write('activityLevel', event.target.value),
            },
            React.createElement('option', { value: 'quiet' }, '安静'),
            React.createElement('option', { value: 'normal' }, '标准'),
            React.createElement('option', { value: 'lively' }, '活泼')),
          ),
          React.createElement(Field, { label: '减少动态效果', hint: '减少走动、循环帧和程序化晃动。' },
            React.createElement('input', {
              type: 'checkbox', checked: value.reducedMotion === true, disabled: !writable,
              onChange: (event) => void write('reducedMotion', event.target.checked),
            }),
          ),
          React.createElement(Field, { label: '提示音', hint: '所有提示的总开关（只影响声音）。' },
            React.createElement('input', {
              type: 'checkbox', checked: value.soundEnabled !== false, disabled: !writable,
              onChange: (event) => void write('soundEnabled', event.target.checked),
            }),
          ),
          React.createElement(SoundPackPicker, {
            value: value.soundPack ?? 'original', disabled: !writable,
            onChange: (next) => write('soundPack', next),
          }),
          value.soundPack === 'custom' ? React.createElement(CustomSoundPicker, { disabled: !writable }) : null,
          value.soundEnabled !== false
            ? React.createElement(Field, { label: '提示音与通知场景', hint: '分别选择对话结束、工具出错和等待审批时是否提示。取消勾选后该场景不再播放提示音；macOS 也不再弹出系统通知横幅。Windows / Linux 只播放声音。' },
                React.createElement(BubbleStatePicker, {
                  value: value.soundStates ?? ['SUCCESS', 'ERROR'],
                  options: SOUND_STATE_OPTIONS,
                  disabled: !writable,
                  onChange: (next) => void write('soundStates', next),
                }),
              )
            : null,
          React.createElement(Field, { label: '气泡显示', hint: '常驻显示、完全隐藏，或自定义哪些状态显示气泡。' },
            React.createElement('select', {
              value: value.bubbleMode ?? 'always', disabled: !writable, style: selectStyle,
              onChange: (event) => void write('bubbleMode', event.target.value),
            },
            React.createElement('option', { value: 'always' }, '常驻显示'),
            React.createElement('option', { value: 'hidden' }, '完全隐藏'),
            React.createElement('option', { value: 'custom' }, '自定义显示状态')),
          ),
          (value.bubbleMode ?? 'always') !== 'hidden'
            ? React.createElement(Field, { label: '气泡大小', hint: `${Math.round((value.bubbleScale ?? 1) * 100)}%` },
                React.createElement('input', {
                  type: 'range', min: 0.8, max: 1.2, step: 0.05, value: value.bubbleScale ?? 1,
                  disabled: status !== 'ready',
                  onChange: (event) => void writeSlider('bubbleScale', Number(event.target.value)),
                }),
              )
            : null,
          React.createElement(Field, { label: '待机文案', hint: '设置桌宠待机时气泡的标题，最多 40 个字。' },
            React.createElement(IdleTitleEditor, {
              value: value.idleTitle ?? '小弟陪大哥待命', disabled: !writable,
              onSave: (next) => void write('idleTitle', next),
            }),
          ),
          React.createElement('details', { style: { border: '1px solid var(--border-color, #d8d8d8)', borderRadius: 8, padding: '10px 12px' } },
            React.createElement('summary', { style: { cursor: 'pointer', fontWeight: 600 } }, '语音输入设置'),
            React.createElement('p', { style: { opacity: 0.72 } }, '桌宠气泡里的“录音”会把识别文字填入输入框；“通话”会在停顿后逐句发送到当前对话，并朗读 DSH 回复。语音识别在本机运行。'),
            React.createElement(Field, { label: '识别服务', hint: 'DSH 内置 SenseVoice 首次使用需要在官方语音输入组件中准备模型。' },
              React.createElement('select', { value: value.voiceEngine ?? 'whisper', disabled: !writable, style: selectStyle,
                onChange: (event) => void write('voiceEngine', event.target.value) },
                React.createElement('option', { value: 'dsh' }, 'DSH 内置 SenseVoice'),
                React.createElement('option', { value: 'whisper' }, '插件本地 Whisper'),
              ),
            ),
            React.createElement(Field, { label: 'Python 路径', hint: '需要安装 torch、transformers、soundfile 和 scipy。' },
              React.createElement(PathEditor, { value: value.voicePython ?? '', disabled: !writable, placeholder: '本地 Python 可执行文件', onSave: (next) => void write('voicePython', next) }),
            ),
            React.createElement(Field, { label: '语音模型', hint: '本地模型目录或已缓存的模型名。' },
              React.createElement(PathEditor, { value: value.voiceModel ?? 'openai/whisper-base', disabled: !writable, placeholder: 'openai/whisper-base', onSave: (next) => void write('voiceModel', next) }),
            ),
            React.createElement(Field, { label: '模型缓存', hint: 'Hugging Face 模型缓存目录，可留空。' },
              React.createElement(PathEditor, { value: value.voiceCache ?? '', disabled: !writable, placeholder: '可选', onSave: (next) => void write('voiceCache', next) }),
            ),
          ),
          (value.bubbleMode ?? 'always') === 'custom'
            ? React.createElement(Field, { label: '自定义显示状态', hint: '勾选后，只有这些状态出现时才会显示气泡。' },
                React.createElement(BubbleStatePicker, {
                  value: value.bubbleStates ?? ['SUCCESS', 'ERROR', 'WAITING'],
                  disabled: !writable,
                  onChange: (next) => void write('bubbleStates', next),
                }),
              )
            : null,
          React.createElement(Field, { label: '响应子 Agent', hint: '默认只跟随顶层任务，避免状态过度跳动。' },
            React.createElement('input', {
              type: 'checkbox', checked: value.includeSubagents === true, disabled: !writable,
              onChange: (event) => void write('includeSubagents', event.target.checked),
            }),
          ),
          React.createElement(Field, { label: '页面内桌宠', hint: '在 DSH 页面右下角显示一只跟随状态的小桌宠（纯装饰）；开关后刷新页面生效。' },
            React.createElement('input', {
              type: 'checkbox', checked: value.webOverlay === true, disabled: !writable,
              onChange: (event) => void write('webOverlay', event.target.checked),
            }),
          ),
          React.createElement(Field, { label: '打开 DSH', hint: '自动识别当前客户端；识别不准时可手动选择。' },
            React.createElement('select', { value: value.clientTarget ?? 'auto', disabled: !writable, style: selectStyle,
              onChange: (event) => void write('clientTarget', event.target.value) },
              React.createElement('option', { value: 'auto' }, '自动识别'),
              React.createElement('option', { value: 'web' }, 'WebUI'),
              React.createElement('option', { value: 'desktop' }, '桌面端'),
            ),
          ),
          React.createElement(Field, { label: '显示余额', hint: '气泡显示总余额，下方可查看赠送／充值明细。' },
            React.createElement('input', { type: 'checkbox', checked: value.balanceEnabled !== false, disabled: !writable,
              onChange: (event) => void write('balanceEnabled', event.target.checked) }),
          ),
          React.createElement(Field, { label: '余额来源', hint: '自动模式优先使用 API Key；账户余额和 API Key 余额可能不同。' },
            React.createElement('select', { value: value.balanceSource ?? 'auto', disabled: !writable, style: selectStyle,
              onChange: (event) => void write('balanceSource', event.target.value) },
              React.createElement('option', { value: 'auto' }, '自动'),
              React.createElement('option', { value: 'api-key' }, 'API Key'),
              React.createElement('option', { value: 'account' }, '已登录账户'),
            ),
          ),
          React.createElement(BalancePanel, { enabled: value.balanceEnabled !== false && value.enabled !== false, source: value.balanceSource ?? 'auto' }),
          busy ? React.createElement('small', { role: 'status' }, '正在保存…') : null,
        ),
    )
  }

  // In-page companion (opt-in via the webOverlay setting). Purely decorative:
  // it mirrors the DSH state as a small looping sprite in the page corner and
  // never blocks or outlives the page. Every failure path ends in "no pet",
  // never in an exception reaching the WebUI.
  function PetOverlay() {
    const [src, setSrc] = useState(null)
    const imageRef = useRef(null)
    useEffect(() => {
      let alive = true
      let raf = 0
      let source = null
      fetch(MANIFEST_ENDPOINT, { cache: 'no-store' })
        .then((response) => (response.ok ? response.json() : Promise.reject(new Error('manifest'))))
        .then((manifest) => {
          if (!alive) return
          const runtime = { name: '', frames: [], frameMs: 42, loop: true, index: 0, base: 'idle', pulseUntil: 0, reducedMotion: false, motionStartedAt: Date.now() }
          let preloader = null
          let spent = 0
          const motionPose = () => {
            const identity = [0, 0, 0, 1, 1]
            if (runtime.reducedMotion) return identity
            const profile = manifest.motionProfiles?.[runtime.name]
            const keys = profile?.keys
            const period = profile?.periodMs
            if (!Array.isArray(keys) || keys.length < 2 || !(period > 0)) return identity
            const elapsed = Math.max(0, Date.now() - runtime.motionStartedAt)
            const position = profile.loop ? elapsed % period : Math.min(elapsed, period)
            for (let i = 0; i < keys.length - 1; i++) {
              const left = keys[i]
              const right = keys[i + 1]
              if (position <= right[0]) {
                const span = right[0] - left[0]
                const amount = span <= 0 ? 0 : Math.max(0, Math.min(1, (position - left[0]) / span))
                const eased = amount * amount * (3 - 2 * amount)
                return left.slice(1).map((value, index) => value + (right[index + 1] - value) * eased)
              }
            }
            return keys[keys.length - 1].slice(1)
          }
          const updateMotion = () => {
            const image = imageRef.current
            if (!image) return
            const [x, y, angle, scaleX, scaleY] = motionPose()
            const pixelScale = 132 / (manifest.maxFrameWidth || 412)
            image.style.transform = `translate(${x * pixelScale}px, ${y * pixelScale}px) rotate(${angle}deg) scale(${scaleX}, ${scaleY})`
          }
          const applyClip = (name) => {
            if (runtime.name === name) return
            const clip = manifest.clips[name] || manifest.clips.idle
            runtime.name = name
            runtime.frames = clip.frames
            runtime.frameMs = clip.frameMs || 42
            runtime.loop = clip.loop !== false
            runtime.index = 0
            runtime.motionStartedAt = Date.now()
            spent = 0
          }
          const frameUrl = (frame) => FRAME_ENDPOINT + '?frame=' + encodeURIComponent(frame)
          const show = () => {
            if (!alive || runtime.frames.length === 0) return
            setSrc(frameUrl(runtime.frames[runtime.index]))
            if (runtime.frames.length > 1 && typeof Image === 'function') {
              try {
                preloader = preloader || new Image()
                preloader.src = frameUrl(runtime.frames[(runtime.index + 1) % runtime.frames.length])
              } catch {}
            }
          }
          applyClip('idle')
          show()
          if (typeof requestAnimationFrame !== 'function') return
          let previous = 0
          const step = (now) => {
            if (!alive) return
            if (runtime.pulseUntil && Date.now() >= runtime.pulseUntil) {
              runtime.pulseUntil = 0
              applyClip(runtime.base)
              previous = now
              show()
            }
            if (previous && !runtime.reducedMotion) {
              spent += now - previous
              if (spent >= runtime.frameMs) {
                const frames = Math.floor(spent / runtime.frameMs)
                spent %= runtime.frameMs
                runtime.index = runtime.loop
                  ? (runtime.index + frames) % runtime.frames.length
                  : Math.min(runtime.index + frames, runtime.frames.length - 1)
                show()
              }
            }
            previous = now
            updateMotion()
            raf = requestAnimationFrame(step)
          }
          raf = requestAnimationFrame(step)
          if (typeof EventSource !== 'undefined') {
            try {
              source = new EventSource(EVENTS_ENDPOINT)
              source.onmessage = (event) => {
                try {
                  const message = JSON.parse(event.data)
                  const clipFor = (state, activity) => state === 'WORKING' && manifest.workingActivityMap?.[activity]
                    || manifest.stateMap[state] || 'idle'
                  if (message.kind === 'config') runtime.reducedMotion = message.reducedMotion === true
                  if (message.kind === 'state' && message.state && manifest.stateMap[message.state]) {
                    runtime.base = clipFor(message.state, message.activity)
                    if (message.state !== 'IDLE') runtime.pulseUntil = 0
                    if (!runtime.pulseUntil) applyClip(runtime.base)
                  }
                  if (message.kind === 'task' && message.state === 'WORKING' && message.activity
                    && manifest.workingActivityMap && manifest.workingActivityMap[message.activity]) {
                    runtime.base = clipFor('WORKING', message.activity)
                    if (!runtime.pulseUntil) applyClip(runtime.base)
                  }
                  if (message.kind === 'pulse' && manifest.stateMap[message.state] && message.ttlMs > 0) {
                    runtime.base = clipFor(message.resumeState, message.resumeActivity)
                    const name = clipFor(message.state)
                    const clip = manifest.clips[name]
                    const duration = runtime.reducedMotion ? 0 : clip.frames.length * clip.frameMs
                    const deadline = runtime.name === name ? runtime.pulseUntil : 0
                    runtime.pulseUntil = Math.max(Date.now() + message.ttlMs, deadline || Date.now() + duration)
                    applyClip(name)
                  }
                  show()
                } catch {}
              }
            } catch {}
          }
        })
        .catch(() => {})
      return () => {
        alive = false
        if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(raf)
        try { source?.close() } catch {}
      }
    }, [])
    if (!src) return null
    return React.createElement('img', {
      ref: imageRef, src, alt: '', 'aria-hidden': true, draggable: false,
      style: {
        position: 'fixed', right: 16, bottom: 12, width: 132, zIndex: 2147483000,
        pointerEvents: 'none', userSelect: 'none', opacity: 0.96, transformOrigin: 'center center',
        filter: 'drop-shadow(0 4px 10px rgba(0,0,0,0.25))',
      },
    })
  }

  function registerWebOverlay(ctx) {
    const registerOverlay = () => {
      try {
        ctx.slots.register({ name: 'shell.overlay', id: 'dsh-dafeilian-overlay', order: 999 }, () =>
          React.createElement(PetOverlay, {}))
      } catch (error) {
        if (typeof console !== 'undefined' && console.error) {
          console.error('[dsh-dafeilian] failed to register web overlay:', error)
        }
      }
    }
    try {
      ctx.slots.inject('shell.overlay', registerOverlay)
    } catch (error) {
      if (typeof console !== 'undefined' && console.error) {
        console.error('[dsh-dafeilian] failed to inject overlay slot:', error)
      }
    }
  }

  function CurrentConversationReporter({ sessionId }) {
    useEffect(() => {
      if (!sessionId) return undefined
      const report = () => {
        void fetch(TASK_TARGET_ENDPOINT, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sessionId }),
        }).catch(() => {})
      }
      report()
      window.addEventListener?.('focus', report)
      return () => window.removeEventListener?.('focus', report)
    }, [sessionId])
    return null
  }

  function apply(ctx) {
    // If DSH changes the slot contract again, fail this card quietly instead of failing the whole
    // WebUI load (that regressed before as 'other plugins stop working').
    // The guard must live INSIDE the inject callback because DSH may invoke
    // it asynchronously, outside any try around the inject() call itself.
    const registerCard = (slot) => () => {
      try {
        ctx.slots.register({
          name: slot, key: 'dsh-dafeilian', id: 'dsh-dafeilian', order: 30,
          label: () => '大肥鱼',
          inject: () => ({}),
        }, BigFishCard)
      } catch (error) {
        if (typeof console !== 'undefined' && console.error) {
          console.error('[dsh-dafeilian] failed to register settings card:', error)
        }
      }
    }
    for (const slot of ['plugins.bundle.config', 'settings.plugins.tab', 'settings.plugin.item']) {
      try {
        ctx.slots.inject(slot, registerCard(slot))
      } catch (error) {
        if (typeof console !== 'undefined' && console.error) {
          console.error('[dsh-dafeilian] failed to inject settings slot:', error)
        }
      }
    }

    // This slot is present only for the selected conversation. Its invisible
    // occupant tells the native pet which Session the user is viewing.
    try {
      ctx.slots.inject('conversation.composer.dock', () => {
        try {
          ctx.slots.register({
            name: 'conversation.composer.dock', id: 'dsh-dafeilian-current-conversation', order: 999,
          }, CurrentConversationReporter)
        } catch (error) {
          console.error?.('[dsh-dafeilian] failed to register current conversation:', error)
        }
      })
    } catch (error) {
      console.error?.('[dsh-dafeilian] failed to inject conversation slot:', error)
    }

    // The in-page pet is opt-in; read the local config once at mount. Any
    // failure (endpoint absent, offline host, closed page) just means no pet.
    try {
      fetch(CONFIG_ENDPOINT, { cache: 'no-store' })
        .then((response) => (response.ok ? response.json() : null))
        .then((config) => {
          if (config && config.webOverlay === true) registerWebOverlay(ctx)
        })
        .catch(() => {})
    } catch {}
  }

  module.exports = {
    name: 'dsh-dafeilian-client',
    inject: ['slots'],
    apply,
  }
  return module.exports
} })
