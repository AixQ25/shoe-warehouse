import { useCallback, useEffect, useState } from 'react'
import CameraScanner from './CameraScanner'
import { newRequestId } from './requestId'
import { api, csrfToken, rejectedSubmission, sessionExpired } from './liveApi'
import { clearPending, readPending, rememberPending } from './pendingOperation'
import type { OperationPayload } from './pendingOperation'
import type { LiveMold, Location, MoldPage, SessionUser } from './liveApi'
import { EmptyState, LoadingSkeleton, StatusBadge } from './WarehouseUI'
import './MobileApp.css'

type ScanResult = { kind: 'MOLD'; mold: LiveMold } | { kind: 'LOCATION'; location: Pick<Location, 'id' | 'code' | 'name' | 'type'> }
type WorkMode = 'ISSUE' | 'RETURN'
type DeviceState = { registered: boolean; id?: number; label?: string; authorized: boolean; revoked?: boolean }
type SubmittedOperation = { id: number; request_id: string; type: WorkMode; items: { mold_code: string }[] }

export default function MobileApp() {
  const canUseLiveCamera = window.isSecureContext && !!navigator.mediaDevices
  const [user, setUser] = useState<SessionUser | null>(null)
  const [checking, setChecking] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<LiveMold[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [selected, setSelected] = useState<ScanResult | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [device, setDevice] = useState<DeviceState | null>(null)
  const [deviceLabel, setDeviceLabel] = useState('我的手机')
  const [targetId, setTargetId] = useState<number | null>(null)
  const [requestId, setRequestId] = useState(newRequestId)
  const [submissionUncertain, setSubmissionUncertain] = useState(false)
  const [pending, setPending] = useState<OperationPayload | null>(null)
  const [pendingOwner, setPendingOwner] = useState<number | null>(null)
  const [pendingError, setPendingError] = useState('')
  const [notice, setNotice] = useState('')
  const [cameraOpen, setCameraOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const workLocked = busy || pending !== null || !!pendingError

  useEffect(() => {
    const expired = () => { setUser(null); setError('登录已失效，请重新登录；待确认请求已保留') }
    window.addEventListener('warehouse-session-expired', expired)
    return () => window.removeEventListener('warehouse-session-expired', expired)
  }, [])

  const acceptSession = useCallback((session: SessionUser) => {
    setUser(session)
    setSelected(null)
    setPendingOwner(session.id)
    try { setPending(readPending(session.id, 'mobile')); setPendingError('') }
    catch (cause) { setPending(null); setPendingError(cause instanceof Error ? cause.message : '待确认请求读取失败') }
  }, [])

  useEffect(() => {
    let alive = true
    api<SessionUser>('/auth/me').then((session) => {
      if (alive) acceptSession(session)
    }).catch((cause) => {
      if (alive && cause instanceof Error && !cause.message.includes('请先登录')) setError(cause.message)
    }).finally(() => { if (alive) setChecking(false) })
    return () => { alive = false }
  }, [acceptSession])

  useEffect(() => {
    if (!user || !['ADMIN', 'WORKER'].includes(user.role)) return
    let alive = true
    void Promise.all([api<Location[]>('/locations'), api<DeviceState>('/devices/current')]).then(([loadedLocations, currentDevice]) => {
      if (alive) { setLocations(loadedLocations); setDevice(currentDevice) }
    }).catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : '作业资料读取失败') })
    return () => { alive = false }
  }, [user])

  function selectMold(mold: LiveMold) {
    if (workLocked) return
    setSelected({ kind: 'MOLD', mold })
    setTargetId(mold.status === 'IN_USE' ? mold.default_location_id : null)
    setRequestId(newRequestId())
    setSubmissionUncertain(false)
    setNotice('')
  }

  async function refreshDevice() {
    try { setDevice(await api<DeviceState>('/devices/current')) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '设备状态读取失败') }
  }

  async function registerDevice() {
    if (!deviceLabel.trim()) { setError('请先填写手机名称'); return }
    setBusy(true)
    setError('')
    try {
      await api('/devices/register', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ label: deviceLabel.trim() }) })
      await refreshDevice()
      setNotice('手机已登记。请在电脑端“系统管理”授权这台设备，然后点“刷新授权状态”。')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '手机登记失败') }
    finally { setBusy(false) }
  }

  async function submitOperation(mold: LiveMold, mode: WorkMode) {
    if (workLocked || !user) return
    if (!device?.authorized) { setError('当前手机尚未授权，不能提交'); return }
    if (!targetId) { setError(mode === 'ISSUE' ? '请选择目标产线' : '请选择归还库位'); return }
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const payload: OperationPayload = { request_id: requestId, type: mode, target_location_id: targetId, items: [{ mold_id: mold.id, expected_version: mold.version }] }
      rememberPending(user.id, 'mobile', payload)
      setPendingOwner(user.id)
      setPending(payload)
      setSubmissionUncertain(true)
      await sendPending(payload, user.id)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '请求保存失败，未发送')
    } finally { setBusy(false) }
  }

  function finishPending(owner: number, result: SubmittedOperation) {
    clearPending(owner, 'mobile')
    setPending(null)
    setSelected(null)
    setTargetId(null)
    setRequestId(newRequestId())
    setSubmissionUncertain(false)
    setNotice(`提交已成功，单据 #${result.id}。请重新扫码核对状态。`)
  }

  async function sendPending(payload: OperationPayload, owner: number) {
    try {
      const result = await api<SubmittedOperation>('/operations', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify(payload) })
      finishPending(owner, result)
    } catch (cause) {
      if (rejectedSubmission(cause)) { clearPending(owner, 'mobile'); setPending(null); setSubmissionUncertain(false) }
      setError(`${cause instanceof Error ? cause.message : '提交失败'}。结果不明时，请查询原提交结果。`)
    }
  }

  async function retryPending() {
    if (busy || !pending || !user || pendingOwner !== user.id) return
    setBusy(true)
    setError('')
    try { await sendPending(pending, user.id) } finally { setBusy(false) }
  }

  async function checkRequest() {
    if (busy || !pending || !user || pendingOwner !== user.id) return
    setBusy(true)
    setError('')
    try {
      const result = await api<SubmittedOperation>(`/operations/by-request/${pending.request_id}`)
      finishPending(user.id, result)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '查询提交结果失败') }
    finally { setBusy(false) }
  }

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const session = await api<SessionUser>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
      acceptSession(session)
      setPassword('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '登录失败')
    } finally { setBusy(false) }
  }

  async function logout() {
    setBusy(true)
    setError('')
    try {
      try { await api('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() } }) }
      catch (cause) { if (!sessionExpired(cause)) throw cause }
      setUser(null)
      setMatches([])
      setTotal(null)
      setSelected(null)
      setLocations([])
      setDevice(null)
      setTargetId(null)
      setNotice('')
      setSubmissionUncertain(false)
      setCameraOpen(false)
      setQuery('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '退出失败')
    } finally { setBusy(false) }
  }

  async function resolveCode(raw: string) {
    if (workLocked) return
    const code = raw.trim()
    if (!code) return
    setBusy(true)
    setError('')
    try {
      const result = await api<ScanResult>('/scan/resolve', { method: 'POST', body: JSON.stringify({ raw_code: code }) })
      if (result.kind === 'MOLD') selectMold(result.mold)
      else { setSelected(result); setTargetId(null); setNotice('') }
      setMatches([])
      setTotal(null)
      setQuery(code)
      setCameraOpen(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '识别失败')
    } finally { setBusy(false) }
  }

  async function search(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (workLocked) return
    const value = query.trim()
    if (!value) { setError('请输入模具、套号或型号'); return }
    if (/^(MOLD|LOC):/i.test(value)) { await resolveCode(value); return }
    setBusy(true)
    setError('')
    setSelected(null)
    try {
      const page = await api<MoldPage>(`/molds?q=${encodeURIComponent(value)}&limit=30`)
      const exact = page.items.find((item) => item.code.toUpperCase() === value.toUpperCase())
      setMatches(page.items)
      setTotal(page.total)
      if (exact) selectMold(exact)
    } catch (cause) {
      setMatches([])
      setTotal(null)
      setError(cause instanceof Error ? cause.message : '查询失败')
    } finally { setBusy(false) }
  }

  async function readPhoto(file: File | undefined) {
    if (!file || workLocked) return
    setBusy(true)
    setError('')
    const url = URL.createObjectURL(file)
    try {
      const { BrowserQRCodeReader } = await import('@zxing/browser')
      const result = await new BrowserQRCodeReader().decodeFromImageUrl(url)
      await resolveCode(result.getText())
    } catch {
      setError('照片中没有识别出模具二维码，请重拍或输入编号')
    } finally {
      URL.revokeObjectURL(url)
      setBusy(false)
    }
  }

  if (checking) return <div className="mobile-app"><div className="mobile-inner"><LoadingSkeleton rows={4} /></div></div>

  if (!user) return <div className="mobile-app mobile-login-screen"><div className="mobile-inner"><div className="mobile-login-mark" aria-hidden="true">▦</div><h1>鞋模具仓库</h1><p>登录后查询模具和扫描标签</p><form className="mobile-login-form" onSubmit={login}><label htmlFor="mobile-username">账号</label><input id="mobile-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /><label htmlFor="mobile-password">密码</label><input id="mobile-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /><button className="mobile-primary" type="submit" disabled={busy}>{busy ? '登录中…' : '登录'}</button></form>{error && <p className="mobile-error" role="alert">{error}</p>}</div></div>

  const selectedMold = selected?.kind === 'MOLD' ? selected.mold : null
  const mode: WorkMode | null = selectedMold?.status === 'READY' ? 'ISSUE' : selectedMold?.status === 'IN_USE' ? 'RETURN' : null
  const canOperate = user.role === 'ADMIN' || user.role === 'WORKER'
  const targets = locations.filter((item) => item.active && item.type === (mode === 'ISSUE' ? 'LINE' : 'SHELF'))

  return <div className="mobile-app"><div className="mobile-inner">
    <header className="mobile-header"><div><span>鞋模具仓库</span><h1>查模具</h1></div><button type="button" onClick={() => void logout()} disabled={busy}>退出</button></header>
    <form className="mobile-search" onSubmit={(event) => void search(event)}><label htmlFor="mobile-query">编号查询</label><div><input id="mobile-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="模具编号、套号或型号" autoComplete="off" /><button className="mobile-primary" type="submit" disabled={busy}>查询</button></div></form>
    <section className="mobile-scan"><div className="mobile-section-title"><h2>扫码</h2><span>扫描标签查看当前信息</span></div><div className="mobile-scan-actions">{canUseLiveCamera && <button className="mobile-primary" type="button" disabled={workLocked} onClick={() => setCameraOpen(!cameraOpen)}>{cameraOpen ? '关闭摄像头' : '实时扫码'}</button>}<label className={`mobile-photo-button${canUseLiveCamera ? '' : ' mobile-photo-primary'}`}>{canUseLiveCamera ? '拍照识别' : '拍照扫码'}<input disabled={workLocked} type="file" accept="image/*" capture="environment" onChange={(event) => { const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; void readPhoto(file) }} /></label></div>{cameraOpen && !workLocked && canUseLiveCamera && <CameraScanner active={cameraOpen} onCode={(code) => void resolveCode(code)} />}</section>
    {busy && <p className="mobile-feedback" role="status">正在读取…</p>}
    {error && <p className="mobile-error" role="alert">{error}</p>}
    {notice && <p className="mobile-feedback" role="status">{notice}</p>}
    {pendingError && <p className="mobile-error" role="alert">{pendingError}</p>}
    {pending && pendingOwner === user.id && <section className="mobile-work"><p>原提交结果待确认：{pending.request_id}</p><button type="button" disabled={busy} onClick={() => void checkRequest()}>查询原提交结果</button><button type="button" disabled={busy} onClick={() => void retryPending()}>按原请求编号重试</button></section>}
    {selected?.kind === 'MOLD' && <section className="mobile-detail"><div className="mobile-section-title"><h2>模具信息</h2><StatusBadge status={selected.mold.status} /></div><strong className="mobile-code">{selected.mold.code}</strong><dl><div><dt>套号</dt><dd>{selected.mold.set_code}</dd></div><div><dt>型号</dt><dd>{selected.mold.model_code}</dd></div><div><dt>尺码</dt><dd>{selected.mold.size_label}</dd></div><div><dt>当前位置</dt><dd>{selected.mold.current_location}</dd></div><div><dt>默认库位</dt><dd>{selected.mold.default_location}</dd></div><div><dt>责任人</dt><dd>{selected.mold.custodian ?? '—'}</dd></div></dl><button className="mobile-refresh" type="button" onClick={() => void resolveCode(selected.mold.code)} disabled={busy}>刷新这件模具</button>{total !== null && <button className="mobile-back-results" type="button" onClick={() => setSelected(null)}>返回查询结果</button>}</section>}
    {selectedMold && mode && canOperate && <section className="mobile-work">
      <div className="mobile-section-title"><h2>{mode === 'ISSUE' ? '领用这件模具' : '完好归还这件模具'}</h2></div>
      <div className="mobile-device-status"><span>当前手机：{device === null ? '正在读取状态' : device.authorized ? `已授权 · ${device.label}` : device.registered && !device.revoked ? '已登记，等待电脑端授权' : '尚未登记'}</span><button type="button" onClick={() => void refreshDevice()} disabled={busy}>刷新授权状态</button></div>
      {device && !device.authorized && (!device.registered || device.revoked) && <div className="mobile-device-register"><label htmlFor="mobile-device-name">手机名称</label><input id="mobile-device-name" value={deviceLabel} maxLength={100} onChange={(event) => setDeviceLabel(event.target.value)} /><button type="button" onClick={() => void registerDevice()} disabled={busy}>登记这台手机</button></div>}
      {device?.registered && !device.authorized && !device.revoked && <p className="mobile-work-hint">请在电脑端“系统管理”授权此设备，然后刷新授权状态。</p>}
      <label className="mobile-target-label" htmlFor="mobile-target">{mode === 'ISSUE' ? '目标产线' : '归还库位'}</label>
      <select id="mobile-target" value={targetId ?? ''} onChange={(event) => { setTargetId(event.target.value ? Number(event.target.value) : null); setRequestId(newRequestId()); setSubmissionUncertain(false) }} disabled={workLocked}>
        <option value="">请选择{mode === 'ISSUE' ? '产线' : '库位'}</option>
        {targets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.code}</option>)}
      </select>
      {mode === 'RETURN' && <p className="mobile-work-hint">此处仅办理完好归还；待检、送修请在电脑端登记。</p>}
      <button className="mobile-primary mobile-submit" type="button" disabled={workLocked || !device?.authorized || !targetId} onClick={() => void submitOperation(selectedMold, mode)}>确认{mode === 'ISSUE' ? '领用' : '完好归还'}</button>
      {submissionUncertain && <button className="mobile-check-request" type="button" disabled={busy} onClick={() => void checkRequest()}>查询本次提交结果</button>}
    </section>}
    {selected?.kind === 'LOCATION' && <section className="mobile-detail"><div className="mobile-section-title"><h2>库位信息</h2></div><strong className="mobile-code">{selected.location.code}</strong><p>{selected.location.name}</p></section>}
    {total !== null && !selected && <section className="mobile-results"><div className="mobile-section-title"><h2>查询结果</h2><span>共 {total} 个</span></div>{matches.length ? matches.map((mold) => <button className="mobile-result" type="button" key={mold.id} onClick={() => selectMold(mold)}><span><strong>{mold.code}</strong><small>{mold.set_code} · {mold.size_label} 码 · {mold.current_location}</small></span><StatusBadge status={mold.status} /></button>) : <EmptyState>没有找到匹配的模具</EmptyState>}{total > matches.length && <p className="mobile-more">仅显示前 {matches.length} 个，请输入更完整的编号。</p>}</section>}
  </div></div>
}
