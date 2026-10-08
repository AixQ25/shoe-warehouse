import { newRequestId } from './requestId'
import { useEffect, useState } from 'react'
import { api, csrfToken } from './liveApi'
import type { LiveMold, Location, SessionUser } from './liveApi'
import { Drawer, StatusBadge } from './WarehouseUI'
import './LiveMoldActions.css'
import { moldLabelRows, moldName } from './moldLabel'

type Action = 'RETURN_FOR_INSPECTION' | 'SEND_REPAIR' | 'REPAIR_COMPLETE' | 'INSPECTION_PASS' | 'SCRAP' | 'FOUND'
const actionNames: Record<Action, string> = { RETURN_FOR_INSPECTION: '异常归还待检', SEND_REPAIR: '送修', REPAIR_COMPLETE: '维修完成', INSPECTION_PASS: '检验通过', SCRAP: '报废', FOUND: '核查找回' }

function availableActions(status: string, role: string): Action[] {
  const ordinary: Action[] = status === 'IN_USE' ? ['RETURN_FOR_INSPECTION', 'SEND_REPAIR'] : status === 'PENDING_INSPECTION' ? ['SEND_REPAIR', 'INSPECTION_PASS'] : status === 'IN_REPAIR' ? ['REPAIR_COMPLETE'] : []
  if (role === 'ADMIN' && status === 'UNVERIFIED') ordinary.push('FOUND')
  if (role === 'ADMIN' && status !== 'SCRAPPED') ordinary.push('SCRAP')
  return ordinary
}

function validTarget(action: Action, foundStatus: 'READY' | 'PENDING_INSPECTION', type: string) {
  if (action === 'RETURN_FOR_INSPECTION') return type === 'SHELF' || type === 'INSPECTION'
  if (action === 'SEND_REPAIR') return type === 'REPAIR'
  if (action === 'REPAIR_COMPLETE') return type === 'INSPECTION'
  if (action === 'INSPECTION_PASS') return type === 'SHELF'
  if (action === 'SCRAP') return type === 'SCRAP'
  return foundStatus === 'READY' ? type === 'SHELF' : type === 'SHELF' || type === 'INSPECTION'
}

export default function LiveMoldActions({ mold, locations, user, onClose, onChanged }: { mold: LiveMold; locations: Location[]; user: SessionUser; onClose: () => void; onChanged: () => Promise<void> }) {
  const actions = availableActions(mold.status, user.role)
  const [action, setAction] = useState<Action | ''>('')
  const [foundStatus, setFoundStatus] = useState<'READY' | 'PENDING_INSPECTION'>('PENDING_INSPECTION')
  const [targetId, setTargetId] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [requestId, setRequestId] = useState(() => newRequestId())
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [authorized, setAuthorized] = useState(user.role === 'ADMIN')
  const targets = action ? locations.filter((item) => item.active && validTarget(action, foundStatus, item.type)) : []

  useEffect(() => {
    if (user.role === 'ADMIN') return
    let alive = true
    void api<{ authorized: boolean }>('/devices/current').then((result) => { if (alive) setAuthorized(result.authorized) }).catch(() => { if (alive) setAuthorized(false) })
    return () => { alive = false }
  }, [user.id, user.role])

  function chooseAction(value: Action | '') {
    setAction(value)
    setTargetId(null)
    setNotice('')
    setRequestId(newRequestId())
  }

  async function submit() {
    if (!action || !targetId || reason.trim().length < 3) { setNotice('请选择操作和目标位置，并填写至少 3 个字的原因'); return }
    setBusy(true)
    try {
      const result = await api<{ operation: { id: number }; mold: LiveMold }>(`/molds/${mold.id}/transition`, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ request_id: requestId, action, expected_version: mold.version, target_location_id: targetId, reason: reason.trim(), found_status: action === 'FOUND' ? foundStatus : null }) })
      setNotice(`${actionNames[action]}已登记，单据 ${result.operation.id}`)
      setRequestId(newRequestId())
      setAction('')
      setTargetId(null)
      setReason('')
      await onChanged()
      if (action === 'SCRAP') onClose()
    } catch (cause) { setNotice(`${cause instanceof Error ? cause.message : '提交失败'}。结果不明时，请保留当前页面并用同一请求编号重试。`) }
    finally { setBusy(false) }
  }

  async function checkRequest() {
    setBusy(true)
    try {
      const result = await api<{ id: number }>(`/operations/by-request/${requestId}`)
      setNotice(`已查到单据 ${result.id}，正在刷新模具状态。`)
      setRequestId(newRequestId())
      setAction('')
      await onChanged()
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : '查询提交结果失败') }
    finally { setBusy(false) }
  }

  return <Drawer title={moldName(mold)} onClose={onClose} className="live-mold-detail">
    <div className="mold-profile">{moldLabelRows({ ...mold, kind: 'MOLD', qr_content: `MOLD:${mold.code}` }).map(([field, value]) => <div key={field}><span>{field}</span><strong>{value}</strong></div>)}</div>
    <div className="mold-profile"><div><span>状态</span><StatusBadge status={mold.status} /></div><div><span>当前位置</span><strong>{mold.current_location}</strong></div><div><span>默认库位</span><strong>{mold.default_location}</strong></div><div><span>当前责任人</span><strong>{mold.custodian ?? '—'}</strong></div></div>
    {user.role !== 'READONLY' && <div className="live-mold-action-panel"><h3>异常状态处理</h3>{user.role !== 'ADMIN' && !authorized && <p>当前设备未授权，不能提交异常操作。</p>}{actions.length ? <><select aria-label="选择异常操作" value={action} onChange={(event) => chooseAction(event.target.value as Action | '')}><option value="">选择适用操作</option>{actions.map((item) => <option value={item} key={item}>{actionNames[item]}</option>)}</select>{action === 'FOUND' && <select aria-label="找回后状态" value={foundStatus} onChange={(event) => { setFoundStatus(event.target.value as 'READY' | 'PENDING_INSPECTION'); setTargetId(null); setRequestId(newRequestId()) }}><option value="PENDING_INSPECTION">先待检</option><option value="READY">确认可用</option></select>}{action && <select aria-label="异常操作目标位置" value={targetId ?? ''} onChange={(event) => { setTargetId(event.target.value ? Number(event.target.value) : null); setRequestId(newRequestId()) }}><option value="">选择实际目标位置</option>{targets.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.code}</option>)}</select>}{action && <textarea aria-label="异常操作原因" value={reason} onChange={(event) => { setReason(event.target.value); setRequestId(newRequestId()) }} placeholder="记录现场检查情况和原因" maxLength={300} rows={3} />}{action && <button className="primary-button" type="button" disabled={busy || !authorized} onClick={() => void submit()}>确认{actionNames[action]}</button>}{action && <button className="secondary-button" type="button" disabled={busy} onClick={() => void checkRequest()}>查询本次提交结果</button>}</> : <p>当前状态没有适用的异常操作。</p>}</div>}
    {notice && <div className="live-work-notice" role="status">{notice}</div>}
  </Drawer>
}
