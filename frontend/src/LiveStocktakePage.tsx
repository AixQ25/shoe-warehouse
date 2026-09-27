import { newRequestId } from './requestId'
import { useEffect, useRef, useState } from 'react'
import CameraScanner from './CameraScanner'
import { api, csrfToken, localTime, stateNames } from './liveApi'
import type { Location, SessionUser } from './liveApi'
import { EmptyState, LoadingSkeleton, StatusBadge } from './WarehouseUI'
import './LiveStocktakePage.css'

interface Expected { mold_id: number; code: string; status: string; version: number }
interface Scan { id: number; code: string; mold_id: number | null; mold_version: number | null; result: 'EXPECTED' | 'WRONG_LOCATION' | 'UNKNOWN'; scanned_at: string }
interface Adjustment { mold_id: number; code: string; type: 'MARK_UNVERIFIED' | 'CONFIRM_WRONG_LOCATION'; operation_id: number; created_at: string }
interface Stocktake { id: number; location_id: number; location_code: string; location_name: string; status: 'ACTIVE' | 'SUBMITTED' | 'CLOSED' | 'CANCELLED'; created_at: string; location_verified: boolean; expected: Expected[]; scans: Scan[]; adjustments: Adjustment[]; missing_codes: string[]; unexpected_codes: string[]; close_reason: string | null }
interface ScanResponse { kind: string; result?: string; stocktake: Stocktake }
interface ResolveResponse { operation: { id: number }; stocktake: Stocktake }

const statusNames: Record<Stocktake['status'], string> = { ACTIVE: '扫码中', SUBMITTED: '待核查', CLOSED: '已完成', CANCELLED: '已取消' }
const scanNames: Record<Scan['result'], string> = { EXPECTED: '相符', WRONG_LOCATION: '错位', UNKNOWN: '未知码' }

export default function LiveStocktakePage({ user, locations, onChanged }: { user: SessionUser; locations: Location[]; onChanged: () => Promise<void> }) {
  const [sessions, setSessions] = useState<Stocktake[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [newLocationId, setNewLocationId] = useState<number | null>(null)
  const [scanCode, setScanCode] = useState('')
  const [reason, setReason] = useState('')
  const [resolutionReason, setResolutionReason] = useState('')
  const [unknownLocationId, setUnknownLocationId] = useState<number | null>(null)
  const resolutionKeys = useRef<Record<string, string>>({})
  const [cameraActive, setCameraActive] = useState(false)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [authorized, setAuthorized] = useState(false)
  const selected = sessions.find((item) => item.id === selectedId)
  const shelves = locations.filter((item) => item.active && item.type === 'SHELF')
  const unknownLocations = locations.filter((item) => item.active && item.type === 'UNKNOWN')

  async function refresh() {
    const [loaded, device] = await Promise.all([api<Stocktake[]>('/stocktakes'), api<{ authorized: boolean }>('/devices/current')])
    setSessions(loaded)
    setAuthorized(device.authorized)
    setSelectedId((current) => current && loaded.some((item) => item.id === current) ? current : loaded[0]?.id ?? null)
  }

  useEffect(() => {
    let alive = true
    void Promise.all([api<Stocktake[]>('/stocktakes'), api<{ authorized: boolean }>('/devices/current')]).then(([loaded, device]) => {
      if (!alive) return
      setSessions(loaded)
      setAuthorized(device.authorized)
      setSelectedId(loaded[0]?.id ?? null)
    }).catch((cause) => { if (alive) setNotice(cause instanceof Error ? cause.message : '盘点任务读取失败') }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  function update(stocktake: Stocktake) {
    setSessions((current) => [stocktake, ...current.filter((item) => item.id !== stocktake.id)].sort((a, b) => b.id - a.id))
    setSelectedId(stocktake.id)
  }

  async function create() {
    if (!newLocationId) { setNotice('请选择盘点库位'); return }
    setBusy(true)
    try {
      const result = await api<Stocktake>('/stocktakes', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ location_id: newLocationId }) })
      update(result)
      setNotice(`已冻结 ${result.location_name}，期初登记 ${result.expected.length} 个模具；请到现场先扫描库位码。`)
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : '创建失败') }
    finally { setBusy(false) }
  }

  async function scan(raw: string) {
    if (!selected || !raw.trim() || busy) return
    setBusy(true)
    try {
      const result = await api<ScanResponse>(`/stocktakes/${selected.id}/scan`, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ raw_code: raw.trim() }) })
      update(result.stocktake)
      setScanCode('')
      setNotice(result.kind === 'LOCATION_VERIFIED' ? '盘点库位已核对' : result.kind === 'ALREADY_SCANNED' ? '这个模具已记录' : result.result === 'EXPECTED' ? '模具与期初清单相符' : result.result === 'WRONG_LOCATION' ? '发现错位，未自动改账' : '未知模具码，未自动建档')
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : '扫码失败') }
    finally { setBusy(false) }
  }

  async function removeScan(scanId: number) {
    if (!selected) return
    setBusy(true)
    try {
      update(await api<Stocktake>(`/stocktakes/${selected.id}/scans/${scanId}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrfToken() } }))
      setNotice('已撤销误扫记录')
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : '撤销失败') }
    finally { setBusy(false) }
  }

  async function action(name: 'submit' | 'close' | 'cancel' | 'reopen') {
    if (!selected) return
    if ((name === 'cancel' || name === 'reopen') && !reason.trim()) { setNotice('请填写原因'); return }
    setBusy(true)
    try {
      const result = await api<Stocktake>(`/stocktakes/${selected.id}/${name}`, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, ...(name === 'cancel' || name === 'reopen' ? { body: JSON.stringify({ reason: reason.trim() }) } : {}) })
      update(result)
      setReason('')
      setCameraActive(false)
      setNotice(name === 'submit' ? '已提交盘点；库位继续冻结，等待维护员核查' : name === 'close' ? '账实一致，盘点已关闭并解除冻结' : name === 'cancel' ? '盘点已取消，库位解除冻结' : '已退回扫码阶段，库位继续冻结')
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }

  async function resolve(type: Adjustment['type'], moldId: number, expectedVersion: number) {
    if (!selected) return
    if (resolutionReason.trim().length < 3) { setNotice('请填写至少 3 个字的核查原因'); return }
    if (type === 'MARK_UNVERIFIED' && !unknownLocationId) { setNotice('请先选择未知位置'); return }
    const key = `${selected.id}:${moldId}:${type}`
    const requestId = resolutionKeys.current[key] ?? newRequestId()
    resolutionKeys.current[key] = requestId
    setBusy(true)
    try {
      const result = await api<ResolveResponse>(`/stocktakes/${selected.id}/resolve`, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ request_id: requestId, type, mold_id: moldId, expected_version: expectedVersion, target_location_id: type === 'MARK_UNVERIFIED' ? unknownLocationId : null, reason: resolutionReason.trim() }) })
      update(result.stocktake)
      delete resolutionKeys.current[key]
      setResolutionReason('')
      setNotice(`核查调整已入账，流转单据 ${result.operation.id}`)
      await onChanged()
    } catch (cause) { setNotice(`${cause instanceof Error ? cause.message : '调整失败'}。如提交结果不明，请保留本页并重试同一项。`) }
    finally { setBusy(false) }
  }

  const scanCodes = new Set(selected?.scans.filter((item) => item.result === 'EXPECTED').map((item) => item.code) ?? [])
  const adjustedMissing = new Set(selected?.adjustments.filter((item) => item.type === 'MARK_UNVERIFIED').map((item) => item.mold_id) ?? [])
  const adjustedWrong = new Set(selected?.adjustments.filter((item) => item.type === 'CONFIRM_WRONG_LOCATION').map((item) => item.mold_id) ?? [])
  return <div className="live-stocktake">
    <div className="live-stocktake-top"><button className="secondary-button" type="button" onClick={() => { void refresh().catch((cause) => setNotice(cause instanceof Error ? cause.message : '刷新失败')) }}>刷新任务</button></div>
    <p className="live-stocktake-note">盘点期间库位流转被冻结。少件和错位由维护员核查后逐件调整；未知码不会自动建档。</p>
    {authorized && <div className="card live-stocktake-create"><select aria-label="新盘点库位" value={newLocationId ?? ''} onChange={(event) => setNewLocationId(event.target.value ? Number(event.target.value) : null)}><option value="">选择盘点库位</option>{shelves.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.code}</option>)}</select><button className="primary-button" type="button" disabled={busy} onClick={() => void create()}>创建盘点</button></div>}
    {!authorized && <p className="live-stocktake-note">当前设备未获作业授权，可查看任务；建单和扫码请使用已授权手机。</p>}
    {notice && <div className="live-work-notice" role="status">{notice}</div>}
    {loading && <LoadingSkeleton rows={4} />}
    <div className="live-stocktake-layout"><aside className="card live-stocktake-list"><strong>最近盘点</strong>{sessions.map((item) => <button type="button" className={selectedId === item.id ? 'active' : ''} key={item.id} onClick={() => { setSelectedId(item.id); setNotice(''); setCameraActive(false) }}><b>{item.location_name}</b><span>#{item.id} · <StatusBadge status={item.status} label={statusNames[item.status]} /></span></button>)}{sessions.length === 0 && <EmptyState>暂无盘点任务</EmptyState>}</aside>
    <section className="card live-stocktake-detail">{selected ? <><div className="live-stocktake-heading"><div><h3>{selected.location_name}</h3><span>#{selected.id} · {localTime(selected.created_at)}</span></div><StatusBadge status={selected.status} label={statusNames[selected.status]} /></div><div className="live-stocktake-counts"><span>期初 {selected.expected.length}</span><span>相符 {scanCodes.size}</span><span>未扫 {selected.missing_codes.length}</span><span>异常 {selected.unexpected_codes.length}</span></div>
      {selected.status === 'ACTIVE' && authorized && <div className="live-stocktake-scan"><p>{selected.location_verified ? '库位已核对，继续扫描模具码' : `请先扫描库位码 LOC:${selected.location_code}`}</p><button type="button" className="text-button" onClick={() => setCameraActive(!cameraActive)}>{cameraActive ? '关闭相机' : '开启相机'}</button><CameraScanner active={cameraActive} onCode={(code) => { void scan(code) }} /><div><input aria-label="盘点扫码输入" value={scanCode} onChange={(event) => setScanCode(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void scan(scanCode) }} placeholder={selected.location_verified ? 'MOLD:M-000001' : `LOC:${selected.location_code}`} /><button className="primary-button" type="button" disabled={busy} onClick={() => void scan(scanCode)}>记录</button></div></div>}
      <div className="live-stocktake-expected"><h4>期初应有清单</h4>{selected.expected.map((item) => <span className={scanCodes.has(item.code) || adjustedMissing.has(item.mold_id) ? 'found' : ''} key={item.mold_id}>{item.code} · {stateNames[item.status] ?? item.status} · {scanCodes.has(item.code) ? '已扫' : adjustedMissing.has(item.mold_id) ? '已核查待找回' : '未扫'}</span>)}{selected.expected.length === 0 && <p>期初账面为空</p>}</div>
      {selected.scans.some((item) => item.result !== 'EXPECTED') && <div className="live-stocktake-differences"><h4>异常扫描</h4>{selected.scans.filter((item) => item.result !== 'EXPECTED').map((item) => <div key={item.id}><span>{item.code} · {scanNames[item.result]}{item.mold_id && adjustedWrong.has(item.mold_id) ? ' · 已调整' : ''}</span>{selected.status === 'ACTIVE' && authorized && <button className="text-button" type="button" disabled={busy} onClick={() => void removeScan(item.id)}>撤销误扫</button>}</div>)}</div>}
      {selected.status === 'SUBMITTED' && user.role === 'ADMIN' && (selected.missing_codes.length > 0 || selected.scans.some((item) => item.result === 'WRONG_LOCATION' && item.mold_id && !adjustedWrong.has(item.mold_id))) && <div className="live-stocktake-resolve"><h4>维护员核查调整</h4><input aria-label="盘点核查原因" value={resolutionReason} onChange={(event) => setResolutionReason(event.target.value)} placeholder="填写现场核查原因" /><select aria-label="未找到模具的未知位置" value={unknownLocationId ?? ''} onChange={(event) => setUnknownLocationId(event.target.value ? Number(event.target.value) : null)}><option value="">未找到模具时，选择未知位置</option>{unknownLocations.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.code}</option>)}</select>{selected.expected.filter((item) => selected.missing_codes.includes(item.code)).map((item) => <div key={item.mold_id}><span>{item.code} · 未扫到</span><button className="secondary-button" type="button" disabled={busy} onClick={() => void resolve('MARK_UNVERIFIED', item.mold_id, item.version)}>核实未找到，标记待核查</button></div>)}{selected.scans.filter((item) => item.result === 'WRONG_LOCATION' && item.mold_id && !adjustedWrong.has(item.mold_id)).map((item) => <div key={item.id}><span>{item.code} · 账面在其他库位</span><button className="secondary-button" type="button" disabled={busy || !item.mold_id || !item.mold_version} onClick={() => { if (item.mold_id && item.mold_version) void resolve('CONFIRM_WRONG_LOCATION', item.mold_id, item.mold_version) }}>确认实物在本库位并调整</button></div>)}</div>}
      {selected.adjustments.length > 0 && <div className="live-stocktake-differences"><h4>已核查调整</h4>{selected.adjustments.map((item) => <div key={item.operation_id}><span>{item.code} · {item.type === 'MARK_UNVERIFIED' ? '待核查' : '错位已调整'}</span><span>单据 {item.operation_id}</span></div>)}</div>}
      <div className="live-stocktake-actions">{selected.status === 'ACTIVE' && authorized && <button className="primary-button" type="button" disabled={busy || !selected.location_verified} onClick={() => void action('submit')}>提交盘点</button>}{selected.status === 'SUBMITTED' && user.role === 'ADMIN' && <button className="primary-button" type="button" disabled={busy || selected.missing_codes.length > 0 || selected.unexpected_codes.length > 0} onClick={() => void action('close')}>无差异，关闭盘点</button>}{user.role === 'ADMIN' && (selected.status === 'ACTIVE' || selected.status === 'SUBMITTED') && <><input aria-label="盘点退回或取消原因" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="退回或取消原因" />{selected.status === 'SUBMITTED' && <button className="secondary-button" type="button" disabled={busy} onClick={() => void action('reopen')}>退回重扫</button>}<button className="secondary-button" type="button" disabled={busy} onClick={() => void action('cancel')}>取消盘点</button></>}</div>
    </> : <p>选择任务查看盘点情况</p>}</section></div>
  </div>
}
