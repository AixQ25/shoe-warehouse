import { newRequestId } from './requestId'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { CSSProperties } from 'react'
import { api, csrfToken } from './liveApi'
import type { LiveMold, Location } from './liveApi'
import { moldLabelRows, moldName, setName } from './moldLabel'
import type { LabelData } from './moldLabel'
import './LiveLabelsPage.css'

type SelectionMode = 'SET' | 'MOLD' | 'LOCATION'
type Label = LabelData
type PrintPurpose = 'INITIAL' | 'REPRINT'
type QrWriter = typeof import('@zxing/browser')['BrowserQRCodeSvgWriter']
type PrintRecord = { id: number; kind: 'MOLD' | 'LOCATION'; purpose: PrintPurpose; codes: string[]; reason: string | null; requested_at: string }

function Qr({ content, Writer }: { content: string; Writer: QrWriter }) {
  const host = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => { host.current?.replaceChildren(new Writer().write(content, 360, 360)) }, [content, Writer])
  return <div className="label-qr" ref={host} aria-label={`二维码 ${content}`} />
}

function LabelCard({ label, Writer, width, height }: { label: Label; Writer: QrWriter; width: number; height: number }) {
  const text = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const element = text.current
    if (!element) return
    element.style.fontSize = ''
    const rows = [...element.children] as HTMLElement[]
    const longest = Math.max(...rows.map((row) => row.scrollWidth))
    if (element.clientWidth > 0 && longest > element.clientWidth) {
      element.style.fontSize = `${parseFloat(getComputedStyle(element).fontSize) * element.clientWidth / longest * 0.98}px`
    }
  }, [label, width, height])
  return <div className="label-card">
    <Qr content={label.qr_content} Writer={Writer} />
    <div className={`label-text ${label.kind === 'LOCATION' ? 'label-location-text' : ''}`} ref={text}>
      {label.kind === 'MOLD' ? moldLabelRows(label).map(([field, value]) => <div className="label-field" key={field}>{field}：{value}</div>) : <><div>{label.code}</div><div>{label.name}</div></>}
    </div>
  </div>
}

export default function LiveLabelsPage({ molds, locations }: { molds: LiveMold[]; locations: Location[] }) {
  const [mode, setMode] = useState<SelectionMode>('SET')
  const [code, setCode] = useState('')
  const [labels, setLabels] = useState<Label[]>([])
  const [writer, setWriter] = useState<QrWriter | null>(null)
  const [width, setWidth] = useState(100)
  const [height, setHeight] = useState(50)
  const [printLayout, setPrintLayout] = useState<'label' | 'sheet'>('label')
  const [gap, setGap] = useState(2)
  const [purpose, setPurpose] = useState<PrintPurpose>('INITIAL')
  const [reason, setReason] = useState('')
  const [requestId, setRequestId] = useState(() => newRequestId())
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [records, setRecords] = useState<PrintRecord[]>([])
  const setCodes = [...new Set(molds.map((item) => item.set_code))].sort()
  const locationCodes = locations.filter((item) => item.active).map((item) => item.code).sort()
  const validSize = Number.isFinite(width) && Number.isFinite(height) && Number.isFinite(gap) && width >= 35 && width <= 150 && height >= 25 && height <= 100 && gap >= 0 && gap <= 15
  const labelStyle = { '--label-width': `${width}mm`, '--label-height': `${height}mm`, '--label-gap': `${gap}mm` } as CSSProperties
  const cards = labels.length > 0 && writer ? labels.map((label) => <LabelCard key={`${label.kind}-${label.code}`} label={label} Writer={writer} width={width} height={height} />) : null

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
      const incomplete = result.labels.some((label) => label.kind === 'MOLD' && moldLabelRows(label).some(([, value]) => value === '—'))
      setNotice(`已生成 ${result.labels.length} 张独立标签预览。${incomplete ? '部分模具标签资料未填写，显示为“—”；可在基础资料中补录。' : '请核对八项资料。'}`)
    } catch (cause) { setLabels([]); setNotice(cause instanceof Error ? cause.message : '预览失败') }
    finally { setBusy(false) }
  }

  async function printLabels() {
    if (!labels.length || !validSize) return
    if ([...document.querySelectorAll<HTMLElement>('.label-print-root .label-text')].some((element) => parseFloat(getComputedStyle(element).fontSize) < 7 * 96 / 72)) {
      setNotice('标签文字过小，请增大标签尺寸或缩短过长的资料后再打印。')
      return
    }
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
      <label>{mode === 'SET' ? '款号与类别' : mode === 'MOLD' ? '款号、类别与码数' : '库位'}<select value={code} onChange={(event) => { setCode(event.target.value); setLabels([]) }}><option value="">请选择</option>{mode === 'SET' ? setCodes.map((value) => <option key={value} value={value}>{setName(molds.find((item) => item.set_code === value)!)}{!molds.find((item) => item.set_code === value)?.mold_category ? ` · ${value}` : ''}</option>) : mode === 'MOLD' ? molds.map((item) => <option key={item.id} value={item.code}>{moldName(item)}</option>) : locationCodes.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <button className="secondary-button" type="button" disabled={busy} onClick={() => void preview()}>生成预览</button>
      <div className="live-label-size"><label>标签宽（毫米）<input type="number" min="35" max="150" value={width} onChange={(event) => setWidth(Number(event.target.value))} /></label><label>标签高（毫米）<input type="number" min="25" max="100" value={height} onChange={(event) => setHeight(Number(event.target.value))} /></label><label>间距（毫米）<input type="number" min="0" max="15" value={gap} onChange={(event) => setGap(Number(event.target.value))} /></label><label>打印纸张<select value={printLayout} onChange={(event) => setPrintLayout(event.target.value as 'label' | 'sheet')}><option value="label">标签纸 · 每页一张</option><option value="sheet">A4 · 多张排版</option></select></label></div>
      <div className="live-label-purpose"><label><input type="radio" checked={purpose === 'INITIAL'} onChange={() => setPurpose('INITIAL')} />首次打印</label><label><input type="radio" checked={purpose === 'REPRINT'} onChange={() => setPurpose('REPRINT')} />补打</label></div>{purpose === 'REPRINT' && <label>补打原因<input value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} placeholder="例如：原标签磨损" /></label>}
      <button className="primary-button" type="button" disabled={busy || !labels.length || !validSize} onClick={() => void printLabels()}>记录请求并打开打印窗口 · {labels.length} 张</button><p>默认 100 × 50 毫米，打印时选择实际纸张、100% 缩放并关闭页眉页脚。二维码仅包含不变的身份编号；印后需抽查扫码。</p>
    </div>
    {notice && <div className="live-work-notice" role="status">{notice}</div>}
    {cards && validSize && <><div className="label-print-sheet" style={labelStyle}>{cards}</div>{createPortal(<div className="label-print-root" data-layout={printLayout} style={labelStyle}><style>{`@media print { @page { size: ${printLayout === 'label' ? `${width}mm ${height}mm` : 'A4'}; margin: ${printLayout === 'label' ? '0' : '4mm'}; } }`}</style><div className="label-print-sheet">{cards}</div></div>, document.body)}</>}
    {records.length > 0 && <div className="card live-label-records"><h3>最近打印请求</h3>{records.map((record) => <div key={record.id}><strong>#{record.id} · {record.purpose === 'REPRINT' ? '补打' : '首次打印'} · {record.kind === 'MOLD' ? '模具' : '库位'} {record.codes.length} 张</strong><span>{new Date(record.requested_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}{record.reason ? ` · ${record.reason}` : ''}</span></div>)}</div>}
  </div>
}
