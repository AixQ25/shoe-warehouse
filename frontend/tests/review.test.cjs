const { test, beforeEach } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')

const tick = () => new Promise((resolve) => setImmediate(resolve))
let storage
beforeEach(() => {
  storage = new Map()
  global.localStorage = { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) }
  global.window = Object.assign(new EventTarget(), { setTimeout, clearTimeout, isSecureContext: false })
  global.document = { cookie: 'warehouse_csrf=test' }
})

function load(name, overrides = {}, cache = {}) {
  if (overrides[name]) return overrides[name]
  if (cache[name]) return cache[name]
  const filename = path.join(__dirname, '../src', name.replace('./', '') + (name.endsWith('Page') || name.endsWith('App') ? '.tsx' : '.ts'))
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText
  const module = { exports: {} }
  cache[name] = module.exports
  new Function('require', 'module', 'exports', code)((dependency) => dependency.endsWith('.css') ? {} : load(dependency, overrides, cache), module, module.exports)
  cache[name] = module.exports
  return module.exports
}

// Exercise the actual component handlers with controlled hooks and transport.
// These are recovery/state tests, not browser layout or camera tests.
const sharedApi = load('./liveApi')

function component(name, api) {
  let cursor = 0
  const state = [], dependencies = [], callbacks = [], pendingEffects = []
  const hooks = {
    useState(initial) {
      const index = cursor++
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial
      return [state[index], (value) => { state[index] = typeof value === 'function' ? value(state[index]) : value }]
    },
    useCallback(callback, values) {
      const index = cursor++
      if (!dependencies[index] || values.some((value, i) => value !== dependencies[index][i])) { dependencies[index] = values; callbacks[index] = callback }
      return callbacks[index]
    },
    useEffect(effect, values) {
      const index = cursor++
      if (!dependencies[index] || values.some((value, i) => value !== dependencies[index][i])) {
        dependencies[index] = values
        pendingEffects.push(effect)
      }
    },
  }
  const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
  const actualApi = sharedApi
  let sequence = 0
  const renderComponent = load(name, { react: hooks, 'react/jsx-runtime': jsx, './liveApi': { ...actualApi, api }, './requestId': { newRequestId: () => `new-request-${++sequence}` }, './CameraScanner': {}, './WarehouseUI': {} }).default
  return {
    render(props) {
      cursor = 0
      const tree = renderComponent(props)
      pendingEffects.splice(0).forEach((effect) => effect())
      return tree
    },
  }
}

function nodes(node) {
  if (!node || typeof node !== 'object') return []
  const children = node.props?.children
  return [node, ...(Array.isArray(children) ? children.flat(Infinity) : [children]).flatMap(nodes)]
}
function text(node) {
  if (node == null) return ''
  if (typeof node !== 'object') return String(node)
  const children = node.props?.children
  return (Array.isArray(children) ? children : [children]).map(text).join('')
}
function button(tree, label) { return nodes(tree).find((node) => node.type === 'button' && text(node).startsWith(label)) }

const mold = { id: 1, code: 'M-1', set_code: 'SET-1', model_code: 'MODEL', name: '测试', size_label: '36', status: 'READY', version: 1, current_location_id: 1, current_location: 'A', default_location_id: 1, default_location: 'A', custodian: null }
const user = { id: 1, username: 'worker', role: 'WORKER', person: '测试人员' }
const locations = [{ id: 1, code: 'A', name: 'A', type: 'SHELF', active: true }, { id: 2, code: 'LINE', name: 'LINE', type: 'LINE', active: true }]
const props = { user, molds: [mold], locations, onChanged: async () => {} }
function seedWork() { localStorage.setItem('warehouse-work-draft-1', JSON.stringify({ mode: 'ISSUE', targetId: 2, codes: ['M-1'], snapshots: [mold], requestId: 'original-request', returns: {} })) }

test('desktop locks an in-flight request and retries its exact persisted payload after remount', async () => {
  seedWork()
  let rejectFirst
  const sent = []
  const api = async (route, init) => {
    if (route === '/devices/current') return { authorized: true }
    sent.push(JSON.parse(init.body))
    if (sent.length === 1) return new Promise((_resolve, reject) => { rejectFirst = reject })
    return { id: 7, items: [{ mold_code: 'M-1' }] }
  }
  let app = component('./LiveWorkPage', api)
  app.render(props); await tick()
  button(app.render(props), '确认领用').props.onClick()
  let tree = app.render(props)
  assert.equal(button(tree, '归还').props.disabled, true)
  button(tree, '归还').props.onClick() // Guard also protects queued callbacks.
  assert.equal(JSON.parse(storage.get('warehouse-work-pending-1')).request_id, 'original-request')
  rejectFirst(new Error('response lost')); await tick()
  app = component('./LiveWorkPage', api)
  app.render({ ...props, molds: [{ ...mold, version: 2 }] }); await tick()
  tree = app.render({ ...props, molds: [{ ...mold, version: 2 }] })
  button(tree, '按原请求编号重试').props.onClick(); await tick()
  assert.deepEqual(sent[1], sent[0])
  assert.equal(sent[1].items[0].expected_version, 1)
  assert.equal(storage.has('warehouse-work-pending-1'), false)
})

test('desktop refresh does not replace the version captured in its cart', async () => {
  seedWork()
  const app = component('./LiveWorkPage', async () => ({ authorized: true }))
  app.render(props); await tick()
  const tree = app.render({ ...props, molds: [{ ...mold, version: 2 }] })
  assert.equal(button(tree, '确认领用').props.disabled, true)
  assert.equal(JSON.parse(storage.get('warehouse-work-draft-1')).snapshots[0].version, 1)
  assert.ok(text(tree).includes('已变化'))
})

test('storage failure prevents sending an inventory request', async () => {
  seedWork()
  let sends = 0
  const app = component('./LiveWorkPage', async (route) => { if (route === '/devices/current') return { authorized: true }; sends++ })
  app.render(props); await tick()
  global.localStorage.setItem = () => { throw new Error('storage unavailable') }
  button(app.render(props), '确认领用').props.onClick(); await tick()
  assert.equal(sends, 0)
})

test('mobile restores pending request after login without needing a selected mold', async () => {
  const pending = { request_id: 'mobile-original', type: 'ISSUE', target_location_id: 2, items: [{ mold_id: 1, expected_version: 1 }] }
  localStorage.setItem('warehouse-mobile-pending-1', JSON.stringify(pending))
  let sent
  const app = component('./MobileApp', async (route, init) => {
    if (route === '/auth/me') return user
    if (route === '/locations') return locations
    if (route === '/devices/current') return { authorized: true }
    if (route === '/operations') { sent = JSON.parse(init.body); return { id: 8, items: [] } }
    throw new Error(route)
  })
  app.render(); await tick()
  app.render(); await tick()
  const tree = app.render()
  button(tree, '按原请求编号重试').props.onClick(); await tick()
  assert.deepEqual(sent, pending)
  assert.equal(storage.has('warehouse-mobile-pending-1'), false)
})

test('401 preserves status and triggers relogin; bad credentials do not expire another session', async () => {
  const { api, ApiError } = sharedApi
  let expired = 0
  window.addEventListener('warehouse-session-expired', () => expired++)
  global.fetch = async () => new Response(JSON.stringify({ detail: { error_code: 'SESSION_EXPIRED', message: '过期' } }), { status: 401 })
  await assert.rejects(api('/devices/current'), (error) => error instanceof ApiError && error.status === 401)
  assert.equal(expired, 1)
  global.fetch = async () => new Response(JSON.stringify({ detail: { error_code: 'BAD_CREDENTIALS' } }), { status: 401 })
  await assert.rejects(api('/auth/login'))
  assert.equal(expired, 1)
})

test('expired-session logout returns the mobile page to its login form', async () => {
  const { ApiError } = sharedApi
  const app = component('./MobileApp', async (route) => {
    if (route === '/auth/me') return user
    if (route === '/locations') return locations
    if (route === '/devices/current') return { authorized: true }
    throw new ApiError('会话已过期', 401, 'SESSION_EXPIRED')
  })
  app.render(); await tick(); app.render(); await tick()
  button(app.render(), '退出').props.onClick(); await tick()
  assert.ok(nodes(app.render()).some((node) => node.type === 'input' && node.props.id === 'mobile-username'))
})

test('legacy desktop draft can query its original result before rescanning', async () => {
  localStorage.setItem('warehouse-work-draft-1', JSON.stringify({ mode: 'ISSUE', targetId: 2, codes: ['M-1'], requestId: 'legacy-request', returns: {} }))
  let queried
  const app = component('./LiveWorkPage', async (route) => {
    if (route === '/devices/current') return { authorized: true }
    queried = route
    return { id: 10, items: [{ mold_code: 'M-1' }] }
  })
  app.render(props); await tick()
  const tree = app.render(props)
  assert.equal(button(tree, '确认领用').props.disabled, true)
  assert.equal(button(tree, '查询本次提交结果').props.disabled, false)
  button(tree, '查询本次提交结果').props.onClick(); await tick()
  assert.equal(queried, '/operations/by-request/legacy-request')
  app.render(props)
  assert.equal(JSON.parse(storage.get('warehouse-work-draft-1')).codes.length, 0)
})

test('uncertain and authorization errors retain pending payload; definite rejection unlocks it', async () => {
  const { ApiError } = sharedApi
  const pending = { request_id: 'original-request', type: 'ISSUE', target_location_id: 2, items: [{ mold_id: 1, expected_version: 1 }] }
  for (const [status, code, retain] of [[401, 'SESSION_EXPIRED', true], [403, 'DEVICE_UNAUTHORIZED', true], [409, 'REQUEST_ID_CONFLICT', true], [503, 'DATABASE_BUSY', true], [409, 'LOCATION_FULL', false]]) {
    seedWork()
    localStorage.setItem('warehouse-work-pending-1', JSON.stringify(pending))
    const app = component('./LiveWorkPage', async (route) => {
      if (route === '/devices/current') return { authorized: true }
      throw new ApiError(code, status, code)
    })
    app.render(props); await tick()
    button(app.render(props), '按原请求编号重试').props.onClick(); await tick()
    assert.equal(storage.has('warehouse-work-pending-1'), retain, code)
    if (retain) assert.deepEqual(JSON.parse(storage.get('warehouse-work-pending-1')), pending)
  }
})

test('API preserves retryable database error and aborts timed-out requests', async () => {
  const { api, ApiError } = sharedApi
  global.fetch = async () => new Response(JSON.stringify({ detail: { error_code: 'DATABASE_BUSY', message: '按原请求编号重试' } }), { status: 503 })
  await assert.rejects(api('/operations'), (error) => error instanceof ApiError && error.status === 503 && error.code === 'DATABASE_BUSY')
  window.setTimeout = (callback) => { queueMicrotask(callback); return 1 }
  global.fetch = (_url, { signal }) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))))
  await assert.rejects(api('/operations'), /请求超时/)
})
