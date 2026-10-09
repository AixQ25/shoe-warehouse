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

function component(name, api, extraOverrides = {}) {
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
    useMemo(factory, values) {
      const index = cursor++
      if (!dependencies[index] || values.some((value, i) => value !== dependencies[index][i])) { dependencies[index] = values; callbacks[index] = factory() }
      return callbacks[index]
    },
    useRef(initial) {
      const index = cursor++
      if (!(index in state)) state[index] = { current: initial }
      return state[index]
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
  const renderComponent = load(name, { react: hooks, 'react/jsx-runtime': jsx, './liveApi': { ...actualApi, api }, './requestId': { newRequestId: () => `new-request-${++sequence}` }, './CameraScanner': {}, './WarehouseUI': {}, './MoldMetadataFields': {}, './MoldMetadataEditor': {}, ...extraOverrides }).default
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

test('master creates a complete style/category through one request without manual model or set numbers', async () => {
  const writes = []
  const ui = component('./LiveMasterPage', async (path, init) => {
    if (init) { writes.push({ path, body: JSON.parse(init.body) }); return { id: 1, created_count: 10 } }
    return []
  })
  const masterProps = { ...props, user: { ...user, role: 'ADMIN' } }
  let tree = ui.render(masterProps)
  await tick()
  function field(label) { return nodes(tree).find((node) => node.type === 'label' && text(node).startsWith(label)).props.children.find((node) => node?.type === 'input' || node?.type === 'select') }
  field('模具编号（款号）').props.onChange({ target: { value: 'QD-264301' } })
  tree = ui.render(masterProps)
  field('模具类别').props.onChange({ target: { value: 'B模' } })
  field('初始库位（仅新增码数）').props.onChange({ target: { value: '1' } })
  tree = ui.render(masterProps)
  const form = nodes(tree).find((node) => node.type === 'form' && text(node).includes('模具建档与生成'))
  form.props.onSubmit({ preventDefault() {} })
  await tick()
  assert.equal(writes.length, 1)
  assert.equal(writes[0].path, '/mold-sets')
  assert.equal(writes[0].body.mold_number, 'QD-264301')
  assert.equal(writes[0].body.mold_category, 'B模')
  assert.equal(writes[0].body.shoe_type, '男鞋')
  assert.equal(writes[0].body.mode, 'SET')
  assert.equal(writes[0].body.default_location_id, 1)
  assert.equal('set_code' in writes[0].body, false)
  assert.equal('mold_code' in writes[0].body, false)
  assert.equal(text(tree).includes('型号'), false)
  assert.equal(text(tree).includes('套号'), false)
})

test('master switches shoe presets and creates one women half-size without obsolete fields', async () => {
  const writes = []
  const ui = component('./LiveMasterPage', async (path, init) => {
    if (init) { writes.push({ path, body: JSON.parse(init.body) }); return { created_count: 1 } }
    return []
  })
  const masterProps = { ...props, user: { ...user, role: 'ADMIN' } }
  let tree = ui.render(masterProps); await tick()
  function change(label, value) {
    tree = ui.render(masterProps)
    const field = nodes(tree).find((node) => node.type === 'label' && text(node).startsWith(label)).props.children.find((node) => node?.type === 'input' || node?.type === 'select')
    field.props.onChange({ target: { value } })
  }
  change('鞋类', '女鞋')
  change('模具编号（款号）', 'W-01')
  button(ui.render(masterProps), '单个生成').props.onClick()
  change('本次生成码数', '35.5')
  change('初始库位', '1')
  tree = ui.render(masterProps)
  nodes(tree).find((node) => node.type === 'form' && text(node).includes('模具建档与生成')).props.onSubmit({ preventDefault() {} })
  await tick()
  assert.equal(writes.length, 1)
  assert.equal(writes[0].body.shoe_type, '女鞋')
  assert.equal(writes[0].body.mode, 'SINGLE')
  assert.equal(writes[0].body.size_label, '35.5')
  assert.deepEqual(writes[0].body.size_labels, ['35.5', '36', '36.5', '37.5', '38', '38.5', '39', '40', '40.5', '41'])
})

test('master exposes deletion for A/B molds and confirms only the selected size', async () => {
  const writes = [], confirmations = []
  let refreshed = 0
  const ui = component('./LiveMasterPage', async (path, init) => {
    if (init) writes.push({ path, init })
    return []
  })
  const member = { ...mold, code: 'QD-264301-B-42.5', mold_number: 'QD-264301', mold_category: 'B模', set_category: 'B模', size_label: '42.5' }
  const masterProps = { ...props, user: { ...user, role: 'ADMIN' }, molds: [member], onChanged: async () => { refreshed++ } }
  window.confirm = (message) => { confirmations.push(message); return false }
  let tree = ui.render(masterProps); await tick()
  button(tree, '删除模具').props.onClick(); await tick()
  assert.equal(writes.length, 0)
  assert.match(confirmations[0], /仅删除这个码数/)
  window.confirm = () => true
  tree = ui.render(masterProps)
  button(tree, '删除模具').props.onClick(); await tick()
  assert.equal(writes.length, 1)
  assert.equal(writes[0].path, '/molds/1')
  assert.equal(writes[0].init.method, 'DELETE')
  assert.equal(writes[0].init.headers['X-CSRF-Token'], 'test')
  assert.equal(refreshed, 1)
  assert.equal(button(ui.render({ ...masterProps, user }), '删除模具'), undefined)
})

test('master displays deletion protection errors without reporting success', async () => {
  const ui = component('./LiveMasterPage', async (_path, init) => {
    if (init) throw new Error('模具已打印标签，不能删除')
    return []
  })
  const masterProps = { ...props, user: { ...user, role: 'ADMIN' }, molds: [{ ...mold, set_category: 'A模' }] }
  window.confirm = () => true
  let tree = ui.render(masterProps); await tick()
  button(tree, '删除模具').props.onClick(); await tick()
  tree = ui.render(masterProps)
  assert.match(text(tree), /模具已打印标签，不能删除/)
  assert.equal(text(tree).includes('已删除'), false)
  assert.equal(button(tree, '删除模具').props.disabled, false)
})

function labelComponent(api, downloads) {
  global.XMLSerializer = class { serializeToString() { return '<svg><path d="M0 0h10v10z"/></svg>' } }
  document.createElementNS = () => ({ setAttribute() {} })
  const Writer = class { write() { return { querySelectorAll: () => [], append() {} } } }
  return component('./LiveLabelsPage', api, {
    'react-dom': { createPortal: (node) => node },
    '@zxing/browser': { BrowserQRCodeSvgWriter: Writer },
    './labelExport': { downloadLabelFile: (blob, filename) => downloads.push({ blob, filename }), labelEditorHtml: () => '<html>editor</html>', labelPdf: async () => new Blob(['pdf']) },
  })
}
async function labelPreview(ui, labelProps) {
  let tree = ui.render(labelProps); await tick()
  const selection = nodes(tree).find((node) => node.type === 'select' && node.props.value === '')
  selection.props.onChange({ target: { value: 'SET-1' } })
  tree = ui.render(labelProps)
  button(tree, '生成预览').props.onClick(); await tick(); await tick()
  return ui.render(labelProps)
}
const labelData = { kind: 'MOLD', code: 'M-1', qr_content: 'MOLD:M-1', name: '测试', size_label: '36', mold_category: 'A模' }
test('label export registers before download, deduplicates concurrent clicks and retries failed registration', async () => {
  const requests = [], downloads = []
  let rejectRegistration
  const ui = labelComponent(async (path, init) => {
    if (path === '/labels/preview') return { labels: [labelData] }
    if (path === '/labels/print-record') { requests.push(JSON.parse(init.body)); if (requests.length === 1) return new Promise((_, reject) => { rejectRegistration = reject }); return { id: 2 } }
    return []
  }, downloads)
  const labelProps = { molds: [mold], locations: [] }
  let tree = await labelPreview(ui, labelProps)
  const output = button(tree, '导出可编辑排版文件')
  assert.equal(output.props.disabled, false)
  output.props.onClick(); output.props.onClick(); await tick()
  assert.equal(requests.length, 1)
  assert.equal(downloads.length, 0)
  rejectRegistration(new Error('服务端超时')); await tick()
  tree = ui.render(labelProps)
  assert.match(text(tree), /服务端超时/)
  button(tree, '导出可编辑排版文件').props.onClick(); await tick()
  assert.deepEqual(requests[1], requests[0])
  assert.equal(downloads.length, 1)
  assert.equal(downloads[0].filename, 'labels-editor-60x25mm.html')
})
test('SVG export records only the shown page and invalid dimensions disable outputs', async () => {
  const requests = [], downloads = []
  const ui = labelComponent(async (path, init) => {
    if (path === '/labels/preview') return { labels: [labelData, { ...labelData, code: 'M-2', qr_content: 'MOLD:M-2' }] }
    if (path === '/labels/print-record') { requests.push(JSON.parse(init.body)); return { id: 1 } }
    return []
  }, downloads)
  const labelProps = { molds: [mold, { ...mold, id: 2, code: 'M-2' }], locations: [] }
  let tree = await labelPreview(ui, labelProps)
  button(tree, '下一页').props.onClick()
  tree = ui.render(labelProps)
  button(tree, '导出当前页 SVG').props.onClick(); await tick()
  assert.deepEqual(requests[0].codes, ['M-2'])
  assert.equal(downloads[0].filename, 'labels-60x25mm-page-2.svg')
  tree = ui.render(labelProps)
  const label = nodes(tree).find((node) => node.type === 'label' && text(node).startsWith('二维码宽高（mm）'))
  label.props.children.find((node) => node?.type === 'input').props.onChange({ target: { value: '30' } })
  tree = ui.render(labelProps)
  assert.equal(button(tree, '导出打印 PDF').props.disabled, true)
  assert.match(text(tree), /二维码或文字超出标签/)
  assert.equal(requests.length, 1)
})
