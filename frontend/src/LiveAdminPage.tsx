import { useCallback, useEffect, useState } from 'react'
import { api, csrfToken, localTime } from './liveApi'
import type { SessionUser } from './liveApi'
import { EmptyState, LoadingSkeleton } from './WarehouseUI'
import './LiveManagement.css'

interface Account { id: number; username: string; role: string; person_id: number | null; person: string | null; active: boolean }
interface Person { id: number; name: string; active: boolean }
interface Device { id: number; username: string; person: string | null; label: string; authorized: boolean; revoked: boolean }
interface Audit { id: number; time: string; action: string; entity: string; before: string | null; after: string | null; reason: string | null }

export default function LiveAdminPage({ user }: { user: SessionUser }) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [audit, setAudit] = useState<Audit[]>([])
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('WORKER')
  const [personId, setPersonId] = useState('')
  const [reason, setReason] = useState('')
  const [statusReason, setStatusReason] = useState('')
  const [resetUserId, setResetUserId] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [loadedAccounts, loadedPeople, loadedDevices, loadedAudit] = await Promise.all([api<Account[]>('/auth/users'), api<Person[]>('/people'), api<Device[]>('/devices'), api<Audit[]>('/auth/audit')])
      setAccounts(loadedAccounts); setPeople(loadedPeople); setDevices(loadedDevices); setAudit(loadedAudit)
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { const load = async () => { if (user.role !== 'ADMIN') return; try { await reload() } catch (cause) { setError(cause instanceof Error ? cause.message : '系统资料读取失败') } }; void load() }, [reload, user.role])

  async function submit(path: string, method: string, body: object | null, success: string) {
    setBusy(true); setError(''); setMessage('')
    try {
      await api(path, { method, headers: { 'X-CSRF-Token': csrfToken() }, ...(body ? { body: JSON.stringify(body) } : {}) })
      await reload()
      setMessage(success)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }

  function confirmDelete(path: string, label: string) {
    if (window.confirm(`确定删除${label}？删除后不能撤销。`)) void submit(path, 'DELETE', null, `${label}已删除`)
  }

  if (user.role !== 'ADMIN') return <div className="card live-restricted">只有系统维护员可以管理账号和设备。</div>

  return <div className="live-management">
    {error && <p className="live-error" role="alert">{error}</p>}{message && <p className="live-note" role="status">{message}</p>}
    {loading && !accounts.length && <LoadingSkeleton />}
    <div className="management-grid">
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/auth/users', 'POST', { username, password, role, person_id: role === 'READONLY' ? null : Number(personId) }, '账号已创建；请将密码安全交给本人') }}><h2>创建账号</h2><label>账号名<input value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label>角色<select value={role} onChange={(event) => setRole(event.target.value)}><option value="WORKER">领用人员</option><option value="ADMIN">系统维护员</option><option value="READONLY">只读</option></select></label>{role !== 'READONLY' && <label>关联人员<select value={personId} onChange={(event) => setPersonId(event.target.value)} required><option value="">选择人员</option>{people.filter((item) => item.active && !accounts.some((account) => account.person_id === item.id)).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}<label>初始密码（至少 6 位）<input type="password" autoComplete="new-password" minLength={6} value={password} onChange={(event) => setPassword(event.target.value)} required /></label><button className="primary-button" disabled={busy}>创建账号</button></form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit(`/auth/users/${resetUserId}/reset-password`, 'POST', { password: newPassword, reason }, '密码已重置；旧登录与设备授权已撤销') }}><h2>重置密码</h2><label>账号<select value={resetUserId} onChange={(event) => setResetUserId(event.target.value)} required><option value="">选择账号</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.username}</option>)}</select></label><label>新密码（至少 6 位）<input type="password" autoComplete="new-password" minLength={6} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required /></label><label>处理原因<input value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} required /></label><button className="primary-button" disabled={busy}>重置密码</button></form>
    </div>
    <section className="card management-list"><h2>账号</h2><p>误建且没有业务记录的账号可删除；已发生业务操作的账号请停用。</p><label className="management-reason">启用或停用原因<input value={statusReason} onChange={(event) => setStatusReason(event.target.value)} minLength={3} /></label><div className="management-set-list">{accounts.map((item) => <div key={item.id}><strong>{item.username} · {item.person ?? '公共只读'}</strong><span>{item.role} · {item.active ? '启用' : '停用'}</span><div className="management-row-actions"><button type="button" disabled={busy || item.id === user.id} onClick={() => { if (statusReason.trim().length < 3) { setError('请先填写至少 3 个字的启用或停用原因'); return } void submit(`/auth/users/${item.id}/active`, 'PATCH', { active: !item.active, reason: statusReason }, item.active ? '账号已停用' : '账号已启用') }}>{item.active ? '停用' : '启用'}</button><button className="management-delete" type="button" disabled={busy || item.id === user.id} onClick={() => confirmDelete(`/auth/users/${item.id}`, `账号 ${item.username}`)}>删除</button></div></div>)}</div></section>
    <section className="card management-list"><h2>授权设备</h2><p>未用于流转登记的设备可删除；已用于业务的设备请撤销授权。</p><div className="management-set-list">{devices.map((item) => <div key={item.id}><strong>{item.person ?? item.username} · {item.label}</strong><span>{item.revoked ? '已撤销' : item.authorized ? '已授权' : '待授权'}</span><div className="management-row-actions">{!item.revoked && <button type="button" disabled={busy} onClick={() => void submit(`/devices/${item.id}/${item.authorized ? 'revoke' : 'authorize'}`, 'POST', null, item.authorized ? '设备已撤销' : '设备已授权')}>{item.authorized ? '撤销' : '授权'}</button>}<button className="management-delete" type="button" disabled={busy} onClick={() => confirmDelete(`/devices/${item.id}`, `设备 ${item.label}`)}>删除</button></div></div>)}{!devices.length && !loading && <EmptyState>暂无登记设备</EmptyState>}</div></section>
    <section className="card management-list"><h2>最近审计</h2><div className="management-set-list">{audit.map((item) => <div key={item.id}><strong>{item.action} · {item.entity}</strong><span>{localTime(item.time)} {item.reason ? `· ${item.reason}` : ''} {item.before || item.after ? `· ${item.before ?? '—'} → ${item.after ?? '—'}` : ''}</span></div>)}{!audit.length && !loading && <EmptyState>暂无审计记录</EmptyState>}</div></section>
  </div>
}
