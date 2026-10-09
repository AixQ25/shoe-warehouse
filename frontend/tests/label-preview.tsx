import React from 'react'
import { createRoot } from 'react-dom/client'
import LiveLabelsPage from '../src/LiveLabelsPage'
import LiveMasterPage from '../src/LiveMasterPage'
import '../src/index.css'
import '../src/App.css'
import '../src/LiveWarehousePage.css'
import { BrowserQRCodeReader } from '@zxing/browser'
import { menSizes } from '../src/shoeSizes'

const mold = { id: 1, code: 'QD-264301-A-42', mold_number: 'QD-264301', shoe_type: '男鞋', expected_size_count: 10, size_label: '42', set_code: 'QD-264301-A', set_category: 'A模', model_code: 'QD-264301', name: '测试模具', status: 'READY', version: 1, current_location_id: 1, current_location: 'A-01-1', default_location_id: 1, default_location: 'A-01-1', custodian: null, manufacturer: '弘晟', mold_category: 'A模', pairs_per_mold: 1, sole_material: 'MD', initial_quarter: '26Q4', opened_on: '2026-03-16' }
const batchMolds = [...menSizes, '46'].map((size, index) => ({ ...mold, id: index + 1, code: `QD-264301-A-${size}`, size_label: size }))
const batchLabels = batchMolds.map((item) => ({ ...item, kind: 'MOLD', qr_content: `MOLD:${item.code}` }))
// Capture generated files without contacting a printer or creating business records.
const originalFetch = window.fetch.bind(window)
const originalClick = HTMLAnchorElement.prototype.click
HTMLAnchorElement.prototype.click = function () {
  if (!this.download) { originalClick.call(this); return }
  const filename = this.download
  void originalFetch(this.href).then((response) => response.arrayBuffer()).then((buffer) => {
    const output = document.getElementById('test-download')!
    output.dataset.filename = filename
    output.textContent = btoa([...new Uint8Array(buffer)].map((byte) => String.fromCharCode(byte)).join(''))
  })
}
window.fetch = async (input, init) => {
  const path = String(input)
  if (init?.method === 'POST' && (path.endsWith('/mold-sets') || path.endsWith('/print-record'))) { document.getElementById('test-request')!.textContent = String(init.body) }
  const body = path.endsWith('/sets') ? [{ id: 1, code: mold.set_code, model_code: mold.model_code, shoe_type: '男鞋', size_labels: menSizes, expected_size_count: 10, mold_category: 'A模', default_location: 'A-01-1', size_count: 10, complete: true }] : path.endsWith('/models') ? [{ id: 1, code: mold.model_code, name: mold.model_code, shoe_type: '男鞋' }] : path.endsWith('/people') ? [] : path.endsWith('/preview') ? { labels: batchLabels.filter((item) => JSON.parse(String(init?.body)).codes.includes(item.code)) } : path.includes('/print-records') ? [] : { id: 1, created_count: init?.body && JSON.parse(String(init.body)).mode === 'SINGLE' ? 1 : 10 }
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
}
export default function TestPage() {
  const [decoded, setDecoded] = React.useState('')
  const [mode, setMode] = React.useState<'label' | 'master'>('label')
  const [batch, setBatch] = React.useState(false)
  async function decode() {
    const svg = document.querySelector('.label-print-page > svg')!
    const uri = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(svg))
    try { setDecoded((await new BrowserQRCodeReader().decodeFromImageUrl(uri)).getText()) }
    catch (cause) { setDecoded(String(cause)) }
  }
  return <div style={{ maxWidth: 1200, margin: '20px auto', padding: 12 }}><h1>隔离界面验证 · 无业务数据库</h1><button onClick={() => setMode('master')}>查看建档界面</button><button onClick={() => setMode('label')}>查看标签界面</button><pre id="test-request" style={{ whiteSpace: 'pre-wrap' }} /><pre id="test-download" hidden />{mode === 'label' ? <><button onClick={() => void decode()}>验证生成二维码</button><button onClick={() => setBatch(!batch)}>切换单张 / 11 张分页样例</button><p>{decoded}</p><LiveLabelsPage key={String(batch)} molds={batch ? batchMolds : [mold]} locations={[]} /></> : <LiveMasterPage user={{ id: 1, username: 'test-admin', role: 'ADMIN', person: '隔离测试' }} molds={[mold]} locations={[{ id: 1, code: 'A-01-1', name: '测试库位', type: 'SHELF', active: true, zone: 'A', rack: '1', level: '1' }]} onChanged={async () => {}} />}</div>
}
const root = createRoot(document.getElementById('root')!)
root.render(<React.StrictMode><TestPage /></React.StrictMode>)
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount())
