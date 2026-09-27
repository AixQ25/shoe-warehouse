import { useCallback, useEffect, useState } from 'react'
import { api, csrfToken } from './liveApi'
import type { Location, SessionUser } from './liveApi'
import { EmptyState, LoadingSkeleton } from './WarehouseUI'
import './LiveManagement.css'

interface Person { id: number; name: string; employee_code: string | null; active: boolean }
interface Model { id: number; code: string; name: string }
interface MoldSet { id: number; code: string; model_code: string; name: string; default_location: string; size_count: number; complete: boolean }

export default function LiveMasterPage({ user, locations, onChanged }: { user: SessionUser; locations: Location[]; onChanged: () => Promise<void> }) {
  const [people, setPeople] = useState<Person[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [sets, setSets] = useState<MoldSet[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [personName, setPersonName] = useState('')
  const [employeeCode, setEmployeeCode] = useState('')
  const [locationCode, setLocationCode] = useState('')
  const [locationName, setLocationName] = useState('')
  const [locationType, setLocationType] = useState('SHELF')
  const [zone, setZone] = useState('')
  const [rack, setRack] = useState('')
  const [level, setLevel] = useState('')
  const [modelCode, setModelCode] = useState('')
  const [modelName, setModelName] = useState('')
  const [setCode, setSetCode] = useState('')
  const [modelId, setModelId] = useState('')
  const [defaultLocationId, setDefaultLocationId] = useState('')
  const [moldCode, setMoldCode] = useState('')
  const [moldSetId, setMoldSetId] = useState('')
  const [size, setSize] = useState('')
  const [moldLocationId, setMoldLocationId] = useState('')
  const [defaultSetId, setDefaultSetId] = useState('')
  const [newDefaultId, setNewDefaultId] = useState('')
  const [reason, setReason] = useState('')
  const [personReason, setPersonReason] = useState('')

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [loadedPeople, loadedModels, loadedSets] = await Promise.all([api<Person[]>('/people'), api<Model[]>('/models'), api<MoldSet[]>('/sets')])
      setPeople(loadedPeople)
      setModels(loadedModels)
      setSets(loadedSets)
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { const load = async () => { try { await reload() } catch (cause) { setError(cause instanceof Error ? cause.message : '基础资料读取失败') } }; void load() }, [reload])

  async function submit(path: string, body: object, success: string, method = 'POST') {
    setBusy(true); setError(''); setMessage('')
    try {
      await api(path, { method, headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify(body) })
      await Promise.all([reload(), onChanged()])
      setMessage(success)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败') }
    finally { setBusy(false) }
  }

  const shelves = locations.filter((item) => item.active && item.type === 'SHELF')
  const locationOptions = <><option value="">选择库位</option>{shelves.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.name}</option>)}</>

  return <div className="live-management">
    {error && <p className="live-error" role="alert">{error}</p>}{message && <p className="live-note" role="status">{message}</p>}
    {loading && !people.length && !models.length && <LoadingSkeleton />}
    {user.role !== 'ADMIN' && <p className="live-note">只有系统维护员可以修改基础资料。</p>}
    {user.role === 'ADMIN' && <div className="management-grid">
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/people', { name: personName, employee_code: employeeCode || null }, '人员已新增') }}><h2>新增人员</h2><label>姓名<input value={personName} onChange={(event) => setPersonName(event.target.value)} required /></label><label>员工编号（可选）<input value={employeeCode} onChange={(event) => setEmployeeCode(event.target.value)} /></label><button className="primary-button" disabled={busy}>保存人员</button></form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/locations', { code: locationCode, name: locationName, type: locationType, zone: locationType === 'SHELF' ? zone : null, rack: locationType === 'SHELF' ? rack : null, level: locationType === 'SHELF' ? level : null }, '位置已新增') }}><h2>新增位置</h2><label>编号<input value={locationCode} onChange={(event) => setLocationCode(event.target.value)} required /></label><label>名称<input value={locationName} onChange={(event) => setLocationName(event.target.value)} required /></label><label>类型<select value={locationType} onChange={(event) => setLocationType(event.target.value)}><option value="SHELF">普通库位</option><option value="LINE">产线</option><option value="INSPECTION">待检区</option><option value="REPAIR">维修区</option><option value="SCRAP">报废区</option><option value="UNKNOWN">未知位置</option></select></label>{locationType === 'SHELF' && <div className="management-inline"><label>区域<input value={zone} onChange={(event) => setZone(event.target.value)} required /></label><label>货架<input value={rack} onChange={(event) => setRack(event.target.value)} required /></label><label>层<input value={level} onChange={(event) => setLevel(event.target.value)} required /></label></div>}<button className="primary-button" disabled={busy}>保存位置</button></form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/models', { code: modelCode, name: modelName.trim() || modelCode }, '型号已新增') }}><h2>新增型号</h2><label>型号编号<input value={modelCode} onChange={(event) => setModelCode(event.target.value)} required /></label><label>型号名称（可选）<input value={modelName} onChange={(event) => setModelName(event.target.value)} /></label><button className="primary-button" disabled={busy}>保存型号</button></form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/sets', { code: setCode, model_id: Number(modelId), default_location_id: Number(defaultLocationId) }, '模具套已新增；请继续建立 10 个尺码档案') }}><h2>新增模具套</h2><label>套号<input value={setCode} onChange={(event) => setSetCode(event.target.value)} required /></label><label>型号<select value={modelId} onChange={(event) => setModelId(event.target.value)} required><option value="">选择型号</option>{models.map((item) => <option value={item.id} key={item.id}>{item.code}</option>)}</select></label><label>默认库位<select value={defaultLocationId} onChange={(event) => setDefaultLocationId(event.target.value)} required>{locationOptions}</select></label><button className="primary-button" disabled={busy}>保存模具套</button></form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/molds', { code: moldCode, set_id: Number(moldSetId), size_label: size, status: 'READY', current_location_id: Number(moldLocationId) }, '单模具已建档') }}><h2>新增单模具</h2><label>模具编号<input value={moldCode} onChange={(event) => setMoldCode(event.target.value)} required /></label><label>所属套<select value={moldSetId} onChange={(event) => setMoldSetId(event.target.value)} required><option value="">选择模具套</option>{sets.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.size_count}/10</option>)}</select></label><label>尺码<input value={size} onChange={(event) => setSize(event.target.value)} required /></label><label>当前位置<select value={moldLocationId} onChange={(event) => setMoldLocationId(event.target.value)} required>{locationOptions}</select></label><button className="primary-button" disabled={busy}>建立模具档案</button></form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit(`/sets/${defaultSetId}/default-location`, { location_id: Number(newDefaultId), reason }, '默认库位已修改；实物位置未改变', 'PATCH') }}><h2>调整默认库位</h2><label>模具套<select value={defaultSetId} onChange={(event) => setDefaultSetId(event.target.value)} required><option value="">选择模具套</option>{sets.map((item) => <option value={item.id} key={item.id}>{item.code} · 当前 {item.default_location}</option>)}</select></label><label>新默认库位<select value={newDefaultId} onChange={(event) => setNewDefaultId(event.target.value)} required>{locationOptions}</select></label><label>原因<input value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} required /></label><p>此操作只改变归还提示，不代表实物已搬动。</p><button className="primary-button" disabled={busy}>确认调整</button></form>
    </div>}
    <section className="card management-list"><h2>现有资料</h2><p>人员 {people.length} · 位置 {locations.length} · 型号 {models.length} · 模具套 {sets.length}</p><div className="management-set-list">{sets.map((item) => <div key={item.id}><strong>{item.code}</strong><span>{item.size_count}/10 个码数 · 默认库位 {item.default_location} {item.complete ? '' : '· 档案未完整'}</span></div>)}{!sets.length && !loading && <EmptyState>暂无模具套资料</EmptyState>}</div></section>
    <section className="card management-list"><h2>人员</h2>{user.role === 'ADMIN' && <label className="management-reason">停用或启用原因<input value={personReason} onChange={(event) => setPersonReason(event.target.value)} minLength={3} /></label>}<div className="management-set-list">{people.map((person) => <div key={person.id}><strong>{person.name}</strong><span>{person.employee_code ?? '无员工编号'} · {person.active ? '启用' : '停用'}</span>{user.role === 'ADMIN' && <button type="button" disabled={busy || person.name === user.person} onClick={() => { if (personReason.trim().length < 3) { setError('请先填写至少 3 个字的处理原因'); return } void submit(`/people/${person.id}/active`, { active: !person.active, reason: personReason }, person.active ? '人员已停用' : '人员已启用', 'PATCH') }}>{person.active ? '停用' : '启用'}</button>}</div>)}</div></section>
  </div>
}
