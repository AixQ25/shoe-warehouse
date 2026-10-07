import { newRequestId } from './requestId'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { api, csrfToken } from './liveApi'
import type { LiveMold, Location } from './liveApi'
import './LiveLabelsPage.css'

type SelectionMode = 'SET' | 'MOLD' | 'LOCATION'
type Label = { kind: 'MOLD' | 'LOCATION'; code: string; qr_content: string; name: string; model_code?: string; set_code?: string; size_label?: string }
type PrintPurpose = 'INITIAL' | 'REPRINT'
type QrWriter = typeof import('@zxing/browser')['BrowserQRCodeSvgWriter']
type PrintRecord = { id: number; kind: 'MOLD' | 'LOCATION'; purpose: PrintPurpose; codes: string[]; reason: string | null; requested_at: string }

function Qr({ content, Writer }: { content: string; Writer: QrWriter }) {
  const host = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => { host.current?.replaceChildren(new Writer().write(content, 180, 180)) }, [content, Writer])
  return <div className="label-qr" ref={host} aria-label={`二维码 ${content}`} />
}

export default function LiveLabelsPage({ molds, locations }: { molds: LiveMold[]; locations: Location[] }) {
  const [mode, setMode] = useState<SelectionMode>('SET')
  const [code, setCode] = useState('')
  const [labels, setLabels] = useState<Label[]>([])
  const [writer, setWriter] = useState<QrWriter | null>(null)
  const [width, setWidth] = useState(55)
  const [height, setHeight] = useState(38)
  const [gap, setGap] = useState(3)
  const [purpose, setPurpose] = useState<PrintPurpose>('INITIAL')
  const [reason, setReason] = useState('')
  const [requestId, setRequestId] = useState(() => newRequestId())
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [records, setRecords] = useState<PrintRecord[]>([])
  const setCodes = [...new Set(molds.map((item) => item.set_code))].sort()
  const locationCodes = locations.filter((item) => item.active).map((item) => item.code).sort()

  useEffect(() => { void api<PrintRecord[]>('/labels/print-records?limit=10').then(setRecords).catch(() => {}) }, [])

  function changeSelection(next: SelectionMode) {
    setMode(next)
    setCode('')
    setLabels([])
    setNotice('')
    setRequestId(newRequestId())
  }

  async function preview() {
    const lookup = code.trim().toUpperCase()
    const selected = mode === 'SET' ? molds.filter((item) => item.set_code.toUpperCase() === lookup).map((item) => item.code) : [mode === 'MOLD' ? molds.find((item) => item.code.toUpperCase() === lookup)?.code : locations.find((item) => item.code.toUpperCase() === lookup && item.active)?.code]
    if (!lookup || selected.length === 0 || selected.some((item) => !item)) { setNotice('没有找到所选编号，请从列表中选择'); return }
    setBusy(true)
    setNotice('')
    try {
      const [result, qrModule] = await Promise.all([api<{ labels: Label[] }>('/labels/preview', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ kind: mode === 'LOCATION' ? 'LOCATION' : 'MOLD', codes: selected }) }), import('@zxing/browser')])
      setWriter(() => qrModule.BrowserQRCodeSvgWriter)
      setLabels(result.labels)
      setRequestId(newRequestId())
      setNotice(`已生成 ${result.labels.length} 张独立标签预览，请检查编号和尺码。`)
    } catch (cause) { setLabels([]); setNotice(cause instanceof Error ? cause.message : '预览失败') }
    finally { setBusy(false) }
  }

  async function printLabels() {
    if (!labels.length) return
    if (purpose === 'REPRINT' && reason.trim().length < 3) { setNotice('补打需填写至少 3 个字的原因'); return }
    setBusy(true)
    setNotice('')
    try {
      const result = await api<{ id: number }>('/labels/print-record', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ request_id: requestId, kind: labels[0].kind, codes: labels.map((item) => item.code), purpose, reason: reason.trim() || null }) })
      setNotice(`已登记打印请求 #${result.id}。请在浏览器打印窗口核对纸张与缩放；取消打印也会保留这条请求记录。`)
      setRequestId(newRequestId())
      void api<PrintRecord[]>('/labels/print-records?limit=10').then(setRecords).catch(() => {})
      window.print()
    } catch (cause) { setNotice(`${cause instanceof Error ? cause.message : '登记失败'}；结果不明时请保留本页并重试。`) }
    finally { setBusy(false) }
  }

  return <div className="live-labels-page">
    <div className="card live-label-controls"><div className="segmented"><button type="button" className={mode === 'SET' ? 'active' : ''} onClick={() => changeSelection('SET')}>整套模具</button><button type="button" className={mode === 'MOLD' ? 'active' : ''} onClick={() => changeSelection('MOLD')}>单个模具</button><button type="button" className={mode === 'LOCATION' ? 'active' : ''} onClick={() => changeSelection('LOCATION')}>库位</button></div>
      <label>{mode === 'SET' ? '套号' : mode === 'MOLD' ? '模具编号' : '位置编号'}<input list="live-label-choices" value={code} onChange={(event) => { setCode(event.target.value); setLabels([]) }} placeholder={mode === 'SET' ? '输入或选择套号' : mode === 'MOLD' ? '输入或选择模具编号' : '输入或选择位置编号'} /></label><datalist id="live-label-choices">{(mode === 'SET' ? setCodes : mode === 'MOLD' ? molds.map((item) => item.code) : locationCodes).map((item) => <option key={item} value={item} />)}</datalist>
      <button className="secondary-button" type="button" disabled={busy} onClick={() => void preview()}>生成预览</button>
      <div className="live-label-size"><label>标签宽（毫米）<input type="number" min="35" max="100" value={width} onChange={(event) => setWidth(Number(event.target.value))} /></label><label>标签高（毫米）<input type="number" min="25" max="80" value={height} onChange={(event) => setHeight(Number(event.target.value))} /></label><label>间距（毫米）<input type="number" min="0" max="15" value={gap} onChange={(event) => setGap(Number(event.target.value))} /></label></div>
      <div className="live-label-purpose"><label><input type="radio" checked={purpose === 'INITIAL'} onChange={() => setPurpose('INITIAL')} />首次打印</label><label><input type="radio" checked={purpose === 'REPRINT'} onChange={() => setPurpose('REPRINT')} />补打</label></div>{purpose === 'REPRINT' && <label>补打原因<input value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} placeholder="例如：原标签磨损" /></label>}
      <button className="primary-button" type="button" disabled={busy || !labels.length || width < 35 || width > 100 || height < 25 || height > 80 || gap < 0 || gap > 15} onClick={() => void printLabels()}>记录请求并打开打印窗口 · {labels.length} 张</button><p>二维码仅包含不变的身份编号。浏览器只能记录打印请求，无法确认标签是否真的印出；印后需抽查扫码。</p>
    </div>
    {notice && <div className="live-work-notice" role="status">{notice}</div>}
    {labels.length > 0 && writer && <div className="label-print-sheet" style={{ '--label-width': `${width}mm`, '--label-height': `${height}mm`, '--label-gap': `${gap}mm` } as CSSProperties}>{labels.map((label) => <div className="label-card" key={`${label.kind}-${label.code}`}><Qr content={label.qr_content} Writer={writer} /><div className="label-text"><strong>{label.code}</strong>{label.kind === 'LOCATION' && <span>{label.name}</span>}{label.kind === 'MOLD' && <><span>{label.model_code} · {label.set_code}</span><b>{label.size_label} 码</b></>}</div></div>)}</div>}
    {records.length > 0 && <div className="card live-label-records"><h3>最近打印请求</h3>{records.map((record) => <div key={record.id}><strong>#{record.id} · {record.purpose === 'REPRINT' ? '补打' : '首次打印'} · {record.kind === 'MOLD' ? '模具' : '库位'} {record.codes.length} 张</strong><span>{new Date(record.requested_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}{record.reason ? ` · ${record.reason}` : ''}</span></div>)}</div>}
  </div>
}
