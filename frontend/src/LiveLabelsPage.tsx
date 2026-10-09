import { newRequestId } from './requestId'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, csrfToken } from './liveApi'
import type { LiveMold, Location } from './liveApi'
import { moldLabelRows, moldName, setName } from './moldLabel'
import type { LabelData } from './moldLabel'
import { compactLabelSettings, createLabelLayout, defaultLabelSettings } from './labelLayout'
import type { EditableLabel, LabelSettings } from './labelLayout'
import { downloadLabelFile, labelEditorHtml, labelPdf } from './labelExport'
import './LiveLabelsPage.css'

type SelectionMode = 'SET' | 'MOLD' | 'LOCATION'
type PrintPurpose = 'INITIAL' | 'REPRINT'
type QrWriter = typeof import('@zxing/browser')['BrowserQRCodeSvgWriter']
type PrintRecord = { id: number; kind: 'MOLD' | 'LOCATION'; purpose: PrintPurpose; codes: string[]; reason: string | null; requested_at: string }
const engine = createLabelLayout()
function qrSvg(content: string, Writer: QrWriter) {
  const svg = new Writer().write(content, 360, 360)
  const rectangles = [...svg.querySelectorAll('rect')].filter((rect) => rect.getAttribute('fill') === '#000000')
  // Paint black modules as one path to avoid raster seams between adjacent tiles.
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  path.setAttribute('fill', '#000000')
  path.setAttribute('d', rectangles.map((rect) => `M${rect.getAttribute('x')} ${rect.getAttribute('y')}h${rect.getAttribute('width')}v${rect.getAttribute('height')}h-${rect.getAttribute('width')}z`).join(''))
  rectangles.forEach((rect) => rect.remove()); svg.append(path)
  return new XMLSerializer().serializeToString(svg)
}

export default function LiveLabelsPage({ molds, locations }: { molds: LiveMold[]; locations: Location[] }) {
  const [mode, setMode] = useState<SelectionMode>('SET')
  const [code, setCode] = useState('')
  const [labels, setLabels] = useState<LabelData[]>([])
  const [writer, setWriter] = useState<QrWriter | null>(null)
  const [settings, setSettings] = useState<LabelSettings>({ ...defaultLabelSettings, ...compactLabelSettings })
  const [pageIndex, setPageIndex] = useState(0)
  const [zoom, setZoom] = useState(0.8)
  const [purpose, setPurpose] = useState<PrintPurpose>('INITIAL')
  const [reason, setReason] = useState('')
  const [requestId, setRequestId] = useState(() => newRequestId())
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)
  const [records, setRecords] = useState<PrintRecord[]>([])
  const setCodes = [...new Set(molds.map((item) => item.set_code))].sort()
  const locationCodes = locations.filter((item) => item.active).map((item) => item.code).sort()
  const editableLabels = useMemo<EditableLabel[]>(() => writer ? labels.map((label) => ({ code: label.code, qrContent: label.qr_content, rows: label.kind === 'MOLD' ? moldLabelRows(label).map(([field, value]) => `${field}：${value}`) : [label.code, label.name], qrSvg: qrSvg(label.qr_content, writer) })) : [], [labels, writer])
  const layout = useMemo(() => {
    try {
      const plan = engine.paginate(editableLabels.length, settings)
      const fonts = editableLabels.map((label) => engine.fontFor(label, settings))
      return { plan, fontSize: fonts.length ? Math.min(...fonts) : settings.fontSize, error: '' }
    } catch (cause) { return { plan: null, fontSize: settings.fontSize, error: cause instanceof Error ? cause.message : '排版参数无效' } }
  }, [editableLabels, settings])
  const shownPage = Math.min(pageIndex, Math.max(0, (layout.plan?.pages.length ?? 1) - 1))
  const canOutput = Boolean(layout.plan?.pages.length) && !layout.error && !busy
  const previewSvg = layout.plan?.pages.length ? engine.pageSvg(editableLabels, settings, shownPage, true) : ''

  useEffect(() => { void api<PrintRecord[]>('/labels/print-records?limit=10').then(setRecords).catch(() => {}) }, [])
  function changeSelection(next: SelectionMode) {
    setMode(next); setCode(''); setLabels([]); setNotice(''); setPageIndex(0); setRequestId(newRequestId())
  }
  function setSize(key: keyof LabelSettings, value: number | string | boolean) {
    setSettings((current) => ({ ...current, [key]: value })); setPageIndex(0)
  }
  async function preview() {
    const lookup = code.trim().toUpperCase()
    const selected = mode === 'SET' ? molds.filter((item) => item.set_code.toUpperCase() === lookup).map((item) => item.code) : [mode === 'MOLD' ? molds.find((item) => item.code.toUpperCase() === lookup)?.code : locations.find((item) => item.code.toUpperCase() === lookup && item.active)?.code]
    if (!lookup || selected.length === 0 || selected.some((item) => !item)) { setNotice('没有找到所选编号，请从列表中选择'); return }
    if (inFlight.current) return
    inFlight.current = true; setBusy(true); setNotice('')
    try {
      const [result, qrModule] = await Promise.all([api<{ labels: LabelData[] }>('/labels/preview', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ kind: mode === 'LOCATION' ? 'LOCATION' : 'MOLD', codes: selected }) }), import('@zxing/browser')])
      setWriter(() => qrModule.BrowserQRCodeSvgWriter); setLabels(result.labels); setPageIndex(0); setRequestId(newRequestId())
      const incomplete = result.labels.some((label) => label.kind === 'MOLD' && moldLabelRows(label).some(([, value]) => value === '—'))
      setNotice(`已生成 ${result.labels.length} 张标签。${incomplete ? '部分资料未填写，显示为“—”。' : '请核对七项资料。'}可导出编辑文件，在文件中调整文字与排版。`)
    } catch (cause) { setLabels([]); setNotice(cause instanceof Error ? cause.message : '预览失败') }
    finally { inFlight.current = false; setBusy(false) }
  }
  async function output(kind: 'print' | 'pdf' | 'html' | 'svg') {
    if (!canOutput || inFlight.current) return
    if (purpose === 'REPRINT' && reason.trim().length < 3) { setNotice('补打需填写至少 3 个字的原因'); return }
    inFlight.current = true; setBusy(true); setNotice('')
    try {
      let blob: Blob | undefined
      const exportedLabels = kind === 'svg' ? layout.plan!.pages[shownPage].positions.map((position) => labels[position.index]) : labels
      if (kind === 'pdf') blob = await labelPdf(editableLabels, settings)
      if (kind === 'html') blob = new Blob([labelEditorHtml(editableLabels, settings)], { type: 'text/html;charset=utf-8' })
      if (kind === 'svg') blob = new Blob([engine.pageSvg(editableLabels, settings, shownPage)], { type: 'image/svg+xml;charset=utf-8' })
      const result = await api<{ id: number }>('/labels/print-record', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ request_id: requestId, kind: labels[0].kind, codes: exportedLabels.map((item) => item.code), purpose, reason: reason.trim() || null }) })
      setRequestId(newRequestId())
      void api<PrintRecord[]>('/labels/print-records?limit=10').then(setRecords).catch(() => {})
      if (kind === 'print') {
        setNotice(`已登记打印请求 #${result.id}。纸张 ${layout.plan!.pageWidth} × ${layout.plan!.pageHeight} mm，请选择实际大小 / 100%；取消打印也会保留请求记录。`)
        window.print()
      } else {
        downloadLabelFile(blob!, `labels-${kind === 'html' ? 'editor-' : ''}${settings.paper === 'a4' ? 'a4-' : ''}${settings.width}x${settings.height}mm${kind === 'svg' ? `-page-${shownPage + 1}` : ''}.${kind}`)
        setNotice(`已登记导出/打印请求 #${result.id}。${kind === 'html' ? '用浏览器打开编辑文件，可离线调整尺寸、位置和文字，保存副本后再打印。' : kind === 'pdf' ? 'PDF 页面尺寸已固定；打印仍请选择实际大小 / 100%，并匹配实际纸张。' : '当前页已导出，SVG 文字与二维码图形可单独编辑，画布单位为毫米。'}`)
      }
    } catch (cause) { setNotice(`${cause instanceof Error ? cause.message : '输出失败'}；登记结果不明时请保留本页并重试。`) }
    finally { inFlight.current = false; setBusy(false) }
  }
  function sizeField(key: Exclude<keyof LabelSettings, 'paper' | 'border'>, label: string, min: number, max: number, disabled = false) {
    return <label>{label}<input type="number" min={min} max={max} step="0.5" disabled={busy || disabled} value={settings[key]} onChange={(event) => setSize(key, Number(event.target.value))} /></label>
  }
  return <div className="live-labels-page">
    <div className="card live-label-selection"><div className="segmented"><button type="button" disabled={busy} className={mode === 'SET' ? 'active' : ''} onClick={() => changeSelection('SET')}>整套模具</button><button type="button" disabled={busy} className={mode === 'MOLD' ? 'active' : ''} onClick={() => changeSelection('MOLD')}>单个模具</button><button type="button" disabled={busy} className={mode === 'LOCATION' ? 'active' : ''} onClick={() => changeSelection('LOCATION')}>库位</button></div>
      <label>{mode === 'SET' ? '款号与类别' : mode === 'MOLD' ? '款号、类别与码数' : '库位'}<select value={code} disabled={busy} onChange={(event) => { setCode(event.target.value); setLabels([]); setRequestId(newRequestId()) }}><option value="">请选择</option>{mode === 'SET' ? setCodes.map((value) => <option key={value} value={value}>{setName(molds.find((item) => item.set_code === value)!)}{!molds.find((item) => item.set_code === value)?.mold_category ? ` · ${value}` : ''}</option>) : mode === 'MOLD' ? molds.map((item) => <option key={item.id} value={item.code}>{moldName(item)}</option>) : locationCodes.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <button className="secondary-button" type="button" disabled={busy} onClick={() => void preview()}>生成预览</button>
    </div>
    {notice && <div className="live-work-notice" role="status">{notice}</div>}
    <div className="label-workspace"><aside className="card live-label-controls">
      <h2>尺寸与排版</h2><p>所有尺寸使用毫米，字号使用磅。设定字号为上限，放不下时自动缩小；实际字号见预览。预览缩放不改变导出尺寸。</p>
      <label>打印纸张<select value={settings.paper} disabled={busy} onChange={(event) => setSize('paper', event.target.value)}><option value="label">标签纸 · 每页一张</option><option value="a4">A4 · 210 × 297 mm</option></select></label>
      <div className="live-label-size">{sizeField('width', '标签宽（mm）', 35, 150)}{sizeField('height', '标签高（mm）', 25, 100)}</div>
      <div className="live-label-size">{sizeField('marginX', '页面左右边距（mm）', 0, 50, settings.paper === 'label')}{sizeField('marginY', '页面上下边距（mm）', 0, 50, settings.paper === 'label')}{sizeField('gap', '标签间距（mm）', 0, 15, settings.paper === 'label')}</div>
      <div className="live-label-size">{sizeField('padding', '标签内边距（mm）', 1, 10)}{sizeField('qrSize', '二维码宽高（mm）', 12, 96)}{sizeField('textGap', '图文间距（mm）', 1, 10)}{sizeField('fontSize', '文字字号（pt）', 5.5, 24)}</div>
      <label>标签外框<select value={settings.border ? 'on' : 'off'} disabled={busy} onChange={(event) => setSize('border', event.target.value === 'on')}><option value="off">无外框</option><option value="on">有外框 · 黑色细线</option></select></label>
      <button className="text-button" type="button" disabled={busy} onClick={() => { setSettings((current) => ({ ...current, ...compactLabelSettings })); setPageIndex(0) }}>使用 60 × 25 紧凑排版</button>
      <button className="text-button" type="button" disabled={busy} onClick={() => { setSettings((current) => ({ ...current, width: 100, height: 50, padding: 2, qrSize: 40, textGap: 2, fontSize: 10.5 })); setPageIndex(0) }}>使用 100 × 50 大标签排版</button>
      {layout.error && <p className="label-layout-error" role="alert">{layout.error}</p>}
      <h2>导出与打印</h2><div className="live-label-purpose"><label><input type="radio" disabled={busy} checked={purpose === 'INITIAL'} onChange={() => setPurpose('INITIAL')} />首次打印</label><label><input type="radio" disabled={busy} checked={purpose === 'REPRINT'} onChange={() => setPurpose('REPRINT')} />补打</label></div>{purpose === 'REPRINT' && <label>补打原因<input value={reason} disabled={busy} maxLength={300} onChange={(event) => setReason(event.target.value)} placeholder="例如：原标签磨损" /></label>}
      <div className="label-export-actions"><button className="primary-button" type="button" disabled={!canOutput} onClick={() => void output('html')}>导出可编辑排版文件</button><button className="secondary-button" type="button" disabled={!canOutput} onClick={() => void output('pdf')}>导出打印 PDF · {labels.length} 张</button><button className="secondary-button" type="button" disabled={!canOutput} onClick={() => void output('svg')}>导出当前页 SVG</button><button className="secondary-button" type="button" disabled={!canOutput} onClick={() => void output('print')}>直接打印 · {labels.length} 张</button></div>
      <p>编辑文件用浏览器打开，可调整文字和排版并保存副本；SVG 保留可编辑文字。PDF 使用固定纸张尺寸和 300 dpi 图像。导出和打印均登记请求。</p><p>打印选择实际纸张、实际大小 / 100%，关闭“适应页面”和页眉页脚；辅助线不会打印，印后请抽查尺寸和扫码。</p>
    </aside><section className="card label-preview-panel"><div className="label-preview-heading"><div><h2>纸张预览</h2><p>毫米标尺 · 橙色为标签边界 · 蓝色为二维码范围</p></div><label>预览缩放<select value={zoom} onChange={(event) => setZoom(Number(event.target.value))}><option value={0.6}>60%</option><option value={0.8}>80%</option><option value={1}>100%</option><option value={1.25}>125%</option></select></label></div>
      {layout.plan && <div className="label-dimensions"><strong>纸张 {layout.plan.pageWidth} × {layout.plan.pageHeight} mm</strong><span>标签 {settings.width} × {settings.height} mm · 二维码 {settings.qrSize} × {settings.qrSize} mm</span><span>每页 {layout.plan.columns} 列 × {layout.plan.rows} 行 · 共 {layout.plan.pages.length} 页{editableLabels.length ? ` · 实际最小字号 ${layout.fontSize.toFixed(1)} pt` : ''}</span></div>}
      {previewSvg && layout.plan ? <><div className="label-page-nav"><button type="button" disabled={shownPage === 0} onClick={() => setPageIndex(shownPage - 1)}>上一页</button><span>第 {shownPage + 1} / {layout.plan.pages.length} 页</span><button type="button" disabled={shownPage >= layout.plan.pages.length - 1} onClick={() => setPageIndex(shownPage + 1)}>下一页</button></div><div className="label-preview-stage"><div className="label-page-preview" style={{ width: (layout.plan.pageWidth + 20) * 96 / 25.4 * zoom, height: (layout.plan.pageHeight + 20) * 96 / 25.4 * zoom }} dangerouslySetInnerHTML={{ __html: previewSvg }} /></div><div className="label-position-list">{layout.plan.pages[shownPage].positions.map((position) => <p key={position.index}>{editableLabels[position.index].code}：左 {position.x} mm，上 {position.y} mm</p>)}</div></> : <div className="label-preview-empty">先选择模具或库位并生成预览。<br />尺寸和位置会在这张纸上实时显示。</div>}
    </section></div>
    {layout.plan?.pages.length ? createPortal(<div className="label-print-root"><style>{`@media print { @page { size: ${layout.plan.pageWidth}mm ${layout.plan.pageHeight}mm; margin: 0; } }`}</style>{layout.plan.pages.map((_, index) => <div className="label-print-page" style={{ width: `${layout.plan!.pageWidth}mm`, height: `${layout.plan!.pageHeight}mm` }} key={index} dangerouslySetInnerHTML={{ __html: engine.pageSvg(editableLabels, settings, index) }} />)}</div>, document.body) : null}
    {records.length > 0 && <div className="card live-label-records"><h3>最近导出 / 打印请求</h3>{records.map((record) => <div key={record.id}><strong>#{record.id} · {record.purpose === 'REPRINT' ? '补打' : '首次打印'} · {record.kind === 'MOLD' ? '模具' : '库位'} {record.codes.length} 张</strong><span>{new Date(record.requested_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}{record.reason ? ` · ${record.reason}` : ''}</span></div>)}</div>}
  </div>
}
