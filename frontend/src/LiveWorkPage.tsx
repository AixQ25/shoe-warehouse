import { newRequestId } from './requestId'
import { useEffect, useState } from 'react'
import CameraScanner from './CameraScanner'
import { api, csrfToken, stateNames } from './liveApi'
import type { LiveMold, Location, SessionUser } from './liveApi'
import './LiveWorkPage.css'

interface DeviceState { registered: boolean; id?: number; label?: string; authorized: boolean; revoked?: boolean }
interface SubmittedOperation { id: number; request_id: string; type: string; items: { mold_code: string }[] }
interface OperationPayload { request_id: string; type: WorkMode; target_location_id: number; items: { mold_id: number; expected_version: number; return_condition?: ReturnCondition; exception_location_id?: number | null; note?: string | null }[] }
type WorkMode = 'ISSUE' | 'RETURN' | 'MOVE' | 'TRANSFER'
type ReturnCondition = 'READY' | 'PENDING_INSPECTION' | 'IN_REPAIR'
interface ReturnChoice { condition: ReturnCondition; locationId: number | null; note: string }
interface WorkDraft { mode: WorkMode; targetId: number | null; codes: string[]; requestId: string; returns: Record<string, ReturnChoice> }
const workNames: Record<WorkMode, string> = { ISSUE: '领用', RETURN: '归还', MOVE: '移库', TRANSFER: '转线' }

function readDraft(userId: number): WorkDraft {
  try {
    const saved = JSON.parse(localStorage.getItem(`warehouse-work-draft-${userId}`) ?? 'null') as Partial<WorkDraft> | null
    if (saved && (saved.mode === 'ISSUE' || saved.mode === 'RETURN' || saved.mode === 'MOVE' || saved.mode === 'TRANSFER') && Array.isArray(saved.codes) && typeof saved.requestId === 'string') {
      const returns: Record<string, ReturnChoice> = {}
      for (const [code, choice] of Object.entries(saved.returns ?? {})) {
        if (choice && ['READY', 'PENDING_INSPECTION', 'IN_REPAIR'].includes(choice.condition)) returns[code] = { condition: choice.condition, locationId: typeof choice.locationId === 'number' ? choice.locationId : null, note: typeof choice.note === 'string' ? choice.note : '' }
      }
      return { mode: saved.mode, targetId: typeof saved.targetId === 'number' ? saved.targetId : null, codes: saved.codes.filter((code): code is string => typeof code === 'string'), requestId: saved.requestId, returns }
    }
  } catch { /* private browsing can disable local storage */ }
  return { mode: 'ISSUE', targetId: null, codes: [], requestId: newRequestId(), returns: {} }
}

export default function LiveWorkPage({ user, molds, locations, onChanged }: { user: SessionUser; molds: LiveMold[]; locations: Location[]; onChanged: () => Promise<void> }) {
  const [initialDraft] = useState(() => readDraft(user.id))
  const [device, setDevice] = useState<DeviceState | null>(null)
  const [deviceLabel, setDeviceLabel] = useState('电脑浏览器')
  const [mode, setMode] = useState<WorkMode>(initialDraft.mode)
  const [targetId, setTargetId] = useState<number | null>(initialDraft.targetId)
  const [codes, setCodes] = useState<string[]>(initialDraft.codes)
  const [returns, setReturns] = useState<Record<string, ReturnChoice>>(initialDraft.returns)
  const [manualCode, setManualCode] = useState('')
  const [cameraActive, setCameraActive] = useState(false)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [requestId, setRequestId] = useState(initialDraft.requestId)
  const targetType = mode === 'ISSUE' || mode === 'TRANSFER' ? 'LINE' : 'SHELF'
  const requiredStatus = mode === 'ISSUE' || mode === 'MOVE' ? 'READY' : 'IN_USE'
  const targets = locations.filter((item) => item.active && item.type === targetType)
  const chosen = codes.map((code) => molds.find((item) => item.code === code)).filter((item): item is LiveMold => Boolean(item))
  const target = locations.find((item) => item.id === targetId)
  const wholeSets = mode === 'RETURN' ? [...new Set(chosen.map((item) => item.set_code))].filter((setCode) => {
    const members = molds.filter((item) => item.set_code === setCode)
    return members.length === 10 && members.every((item) => codes.includes(item.code) && (returns[item.code]?.condition ?? 'READY') === 'READY') && members[0].default_location_id !== targetId
  }) : []

  async function loadDevices() {
    try {
      const current = await api<DeviceState>('/devices/current')
      setDevice(current)
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : '设备状态读取失败')
    }
  }

  useEffect(() => {
    let alive = true
    void api<DeviceState>('/devices/current').then((value) => { if (alive) setDevice(value) }).catch((cause) => { if (alive) setNotice(cause instanceof Error ? cause.message : '设备状态读取失败') })
    return () => { alive = false }
  }, [user.id])

  useEffect(() => {
    try { localStorage.setItem(`warehouse-work-draft-${user.id}`, JSON.stringify({ mode, targetId, codes, requestId, returns })) } catch { /* manual retry still works during this page session */ }
  }, [user.id, mode, targetId, codes, requestId, returns])

  function resetRequest() { setRequestId(newRequestId()) }

  function updateReturn(code: string, patch: Partial<ReturnChoice>) {
    setReturns((previous) => ({ ...previous, [code]: { ...(previous[code] ?? { condition: 'READY', locationId: null, note: '' }), ...patch } }))
    resetRequest()
  }

  function changeMode(next: WorkMode) {
    setMode(next)
    setTargetId(null)
    setCodes([])
    setReturns({})
    setManualCode('')
    setCameraActive(false)
    setNotice('')
    resetRequest()
  }

  function scan(raw: string) {
    const value = raw.trim().toUpperCase()
    if (!value) return
    if (value.startsWith('LOC:') || locations.some((item) => item.code.toUpperCase() === value)) {
      const code = value.replace(/^LOC:/, '')
      const location = locations.find((item) => item.code.toUpperCase() === code && item.type === targetType && item.active)
      if (!location) { setNotice(`当前操作需要扫描${targetType === 'LINE' ? '产线' : '库位'}二维码`); return }
      setTargetId(location.id)
      setNotice(`目标位置：${location.name}`)
      setManualCode('')
      resetRequest()
      return
    }
    const code = value.replace(/^MOLD:/, '')
    const mold = molds.find((item) => item.code.toUpperCase() === code)
    if (!mold) { setNotice('没有找到这个模具编号，请刷新数据或核对标签'); return }
    if (codes.includes(mold.code)) { setNotice('这个模具已加入清单'); return }
    if (mold.status !== requiredStatus) { setNotice(`${mold.code} 当前${stateNames[mold.status] ?? mold.status}，不能${workNames[mode]}`); return }
    setCodes((previous) => [...previous, mold.code])
    if (mode === 'RETURN') setReturns((previous) => ({ ...previous, [mold.code]: { condition: 'READY', locationId: null, note: '' } }))
    if (mode === 'RETURN' && targetId === null) setTargetId(mold.default_location_id)
    setNotice(`已加入 ${mold.code} · ${mold.size_label}码`)
    setManualCode('')
    resetRequest()
  }

  async function registerDevice() {
    if (!deviceLabel.trim()) { setNotice('请给当前设备填写一个名称'); return }
    setBusy(true)
    try {
      await api('/devices/register', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ label: deviceLabel.trim() }) })
      await loadDevices()
      setNotice('已登记当前浏览器设备，等待维护员授权')
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : '设备登记失败')
    } finally { setBusy(false) }
  }

  async function submit() {
    if (!device?.authorized) { setNotice('当前设备尚未授权，不能提交'); return }
    const hasNormalReturn = mode === 'RETURN' && chosen.some((item) => (returns[item.code]?.condition ?? 'READY') === 'READY')
    const operationTargetId = mode === 'RETURN' && !hasNormalReturn ? returns[chosen[0]?.code]?.locationId : target?.id
    if (!operationTargetId || !chosen.length || chosen.length !== codes.length) { setNotice('请确认目标位置和模具清单'); return }
    if (mode === 'RETURN' && chosen.some((item) => {
      const choice = returns[item.code]
      return choice && choice.condition !== 'READY' && (!choice.locationId || choice.note.trim().length < 3)
    })) { setNotice('异常归还的每件模具都要选择实际位置，并填写至少 3 个字的原因'); return }
    setBusy(true)
    try {
      const payload: OperationPayload = { request_id: requestId, type: mode, target_location_id: operationTargetId, items: chosen.map((item) => ({ mold_id: item.id, expected_version: item.version, ...(mode === 'RETURN' ? { return_condition: returns[item.code]?.condition ?? 'READY', exception_location_id: returns[item.code]?.locationId ?? null, note: returns[item.code]?.note.trim() || null } : {}) })) }
      const result = await api<SubmittedOperation>('/operations', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify(payload) })
      setNotice(`${workNames[mode]}登记成功：单据 ${result.id}，${result.items.length} 个模具`)
      setCodes([])
      setReturns({})
      setCameraActive(false)
      resetRequest()
      await onChanged()
    } catch (cause) {
      setNotice(`${cause instanceof Error ? cause.message : '提交失败'}。如结果不明，请先查询本次提交结果。`)
    } finally { setBusy(false) }
  }

  async function checkRequest() {
    setBusy(true)
    try {
      const result = await api<SubmittedOperation>(`/operations/by-request/${requestId}`)
      setNotice(`已查到单据 ${result.id}，登记 ${result.items.length} 个模具。库存正在刷新。`)
      setCodes([])
      setReturns({})
      setCameraActive(false)
      resetRequest()
      await onChanged()
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : '查询提交结果失败')
    } finally { setBusy(false) }
  }

  return <div className="live-work">
    <div className="live-work-head"><strong>操作人：{user.person ?? user.username}</strong><button className="secondary-button" type="button" onClick={() => { void loadDevices(); void onChanged() }}>刷新状态</button></div>
    <div className="live-device card"><strong>当前设备</strong><span>{device === null ? '正在读取…' : device.authorized ? `已授权 · ${device.label}` : device.registered && !device.revoked ? `待授权 · ${device.label}（请维护员到系统管理授权）` : device.revoked ? '授权已撤销，请重新登记' : '尚未登记'}</span>{device && !device.authorized && <div><input aria-label="设备名称" value={deviceLabel} onChange={(event) => setDeviceLabel(event.target.value)} maxLength={100} /><button className="secondary-button" type="button" disabled={busy} onClick={() => void registerDevice()}>登记当前设备</button></div>}</div>
    <div className="segmented">{(['ISSUE', 'RETURN', 'MOVE', 'TRANSFER'] as WorkMode[]).map((item) => <button key={item} type="button" className={mode === item ? 'active' : ''} onClick={() => changeMode(item)}>{workNames[item]}</button>)}</div>
    <div className="live-work-grid"><div className="card live-work-card"><label htmlFor="live-target">{targetType === 'LINE' ? '目标产线' : mode === 'RETURN' ? '完好件归还库位' : '目标库位'}</label><select id="live-target" value={targetId ?? ''} onChange={(event) => { setTargetId(event.target.value ? Number(event.target.value) : null); resetRequest() }}><option value="">请选择，或扫描位置码</option>{targets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.code}</option>)}</select>{(mode === 'RETURN' || mode === 'MOVE') && target && <p>这个库位已存 {molds.filter((item) => item.current_location_id === target.id).length}/10 个模具；最多存放 10 个。</p>}{mode === 'RETURN' && <p>异常件在下方逐件选择待检区或维修区，并填写原因。</p>}{mode === 'TRANSFER' && <p>转线成功后，当前登录人员将成为这些模具的责任人。</p>}</div><div className="card live-work-card"><div className="live-work-scan-head"><strong>模具或位置编号</strong><button className="text-button" type="button" onClick={() => setCameraActive(!cameraActive)}>{cameraActive ? '关闭相机' : '摄像头扫描'}</button></div><CameraScanner active={cameraActive} onCode={scan} /><div className="live-manual"><input aria-label="输入模具或位置编号" placeholder="M-000001 或 LOC:A-01-1" value={manualCode} onChange={(event) => setManualCode(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') scan(manualCode) }} /><button className="primary-button" type="button" onClick={() => scan(manualCode)}>加入</button></div></div></div>
    {notice && <div className="live-work-notice" role="status">{notice}</div>}
    <div className="card live-work-list"><h3>本次清单 · {chosen.length} 个</h3>{chosen.map((item) => { const choice = returns[item.code] ?? { condition: 'READY', locationId: null, note: '' }; return <div className="live-work-item" key={item.code}><span><strong>{item.code} · {item.size_label}码</strong><small>{item.set_code} · {item.current_location}</small></span>{mode === 'RETURN' && <div className="live-return-fields"><select aria-label={`${item.code} 归还结果`} value={choice.condition} onChange={(event) => updateReturn(item.code, { condition: event.target.value as ReturnCondition, locationId: null, note: '' })}><option value="READY">完好入库</option><option value="PENDING_INSPECTION">待检</option><option value="IN_REPAIR">送修</option></select>{choice.condition !== 'READY' && <><select aria-label={`${item.code} 异常目标位置`} value={choice.locationId ?? ''} onChange={(event) => updateReturn(item.code, { locationId: event.target.value ? Number(event.target.value) : null })}><option value="">选择实际位置</option>{locations.filter((location) => location.active && location.type === (choice.condition === 'PENDING_INSPECTION' ? 'INSPECTION' : 'REPAIR')).map((location) => <option key={location.id} value={location.id}>{location.name} · {location.code}</option>)}</select><input aria-label={`${item.code} 异常原因`} value={choice.note} maxLength={300} placeholder="填写异常原因" onChange={(event) => updateReturn(item.code, { note: event.target.value })} /></>}</div>}<button className="text-button" type="button" onClick={() => { setCodes((previous) => previous.filter((code) => code !== item.code)); setReturns((previous) => { const next = { ...previous }; delete next[item.code]; return next }); resetRequest() }}>移除</button></div> })}{chosen.length === 0 && <p>扫码或输入编号后，模具会出现在这里。</p>}</div>
    {wholeSets.length > 0 && <p className="live-work-note">本次有 {wholeSets.length} 套完整归还到新库位，成功提交后默认库位也将变更。</p>}
    <div className="live-work-actions"><button className="primary-button" type="button" disabled={busy || !chosen.length || (mode !== 'RETURN' && !target) || !device?.authorized} onClick={() => void submit()}>确认{workNames[mode]} · {chosen.length} 个</button><button className="secondary-button" type="button" disabled={busy || !chosen.length} onClick={() => void checkRequest()}>查询本次提交结果</button></div>
  </div>
}
