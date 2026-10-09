import { useCallback, useEffect, useState } from 'react'
import { api, csrfToken } from './liveApi'
import type { LiveMold, Location, SessionUser } from './liveApi'
import { EmptyState, LoadingSkeleton } from './WarehouseUI'
import './LiveManagement.css'
import MoldMetadataFields from './MoldMetadataFields'
import { metadataForm, metadataPayload } from './moldMetadataForm'
import MoldMetadataEditor from './MoldMetadataEditor'
import { moldName, setName } from './moldLabel'
import { shoeTypes, sizePresets, bigKidsSizes, littleKidsSizes, menSizes, parseSizeList } from './shoeSizes'
import type { ShoeType } from './shoeSizes'

interface Person { id: number; name: string; employee_code: string | null; active: boolean }
interface Model { id: number; code: string; name: string; shoe_type?: ShoeType | null }
interface MoldSet { id: number; code: string; model_code: string; mold_category: string | null; shoe_type?: ShoeType | null; size_labels?: string[]; expected_size_count?: number | null; name: string; default_location: string; size_count: number; complete: boolean }
const locationTypeNames: Record<string, string> = { SHELF: '普通库位', LINE: '产线', INSPECTION: '待检区', REPAIR: '维修区', SCRAP: '报废区', UNKNOWN: '未知位置' }

export default function LiveMasterPage({ user, locations, molds, onChanged }: { user: SessionUser; locations: Location[]; molds: LiveMold[]; onChanged: () => Promise<void> }) {
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
  const [locationQuery, setLocationQuery] = useState('')
  const [moldQuery, setMoldQuery] = useState('')
  const [zone, setZone] = useState('')
  const [rack, setRack] = useState('')
  const [level, setLevel] = useState('')
  const [moldNumber, setMoldNumber] = useState('')
  const [category, setCategory] = useState('A模')
  const [shoeType, setShoeType] = useState<ShoeType>('男鞋')
  const [generationMode, setGenerationMode] = useState<'SET' | 'SINGLE'>('SET')
  const [sizeText, setSizeText] = useState(menSizes.join('、'))
  const [singleSize, setSingleSize] = useState('')
  const [defaultLocationId, setDefaultLocationId] = useState('')
  const [newMetadata, setNewMetadata] = useState(() => metadataForm())
  const [editingMold, setEditingMold] = useState<LiveMold | null>(null)
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

  async function submit(path: string, body: object, success: string | ((result: { created_count: number }) => string), method = 'POST') {
    setBusy(true); setError(''); setMessage('')
    try {
      const result = await api<{ created_count: number }>(path, { method, headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify(body) })
      await Promise.all([reload(), onChanged()])
      setMessage(typeof success === 'string' ? success : success(result))
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败') }
    finally { setBusy(false) }
  }

  function chooseType(next: ShoeType) { setShoeType(next); setSizeText(sizePresets[next].join('、')); setSingleSize('') }
  function chooseIdentity(number: string, nextCategory: string) {
    setMoldNumber(number); setCategory(nextCategory)
    const model = models.find((item) => item.code.toUpperCase() === number.trim().toUpperCase())
    const existing = sets.find((item) => item.model_code.toUpperCase() === number.trim().toUpperCase() && item.mold_category === nextCategory)
    if (model?.shoe_type) setShoeType(model.shoe_type)
    if (existing?.size_labels?.length) setSizeText(existing.size_labels.join('、'))
    else if (model?.shoe_type) setSizeText(sizePresets[model.shoe_type].join('、'))
    setSingleSize('')
  }
  async function generate() {
    try {
      const sizes = parseSizeList(sizeText)
      if (generationMode === 'SINGLE' && (!singleSize || !sizes.includes(String(Number(singleSize.replace(/[#＃]+$/, '')))))) throw new Error('请选择该套清单中的一个码数')
      await submit('/mold-sets', { mold_number: moldNumber.trim(), shoe_type: shoeType, mold_category: category, mode: generationMode, size_labels: sizes, ...(generationMode === 'SINGLE' ? { size_label: singleSize } : {}), default_location_id: Number(defaultLocationId), ...metadataPayload(newMetadata) }, (result) => `${moldNumber.trim().toUpperCase()} · ${category} 本次新增 ${result.created_count} 个码数，已有模具保留`)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '码数填写有误') }
  }

  async function remove(path: string, label: string, onSuccess?: () => void, confirmation?: string) {
    if (!window.confirm(confirmation ?? `确定删除${label}？删除后不能撤销。`)) return
    setBusy(true); setError(''); setMessage('')
    try {
      await api(path, { method: 'DELETE', headers: { 'X-CSRF-Token': csrfToken() } })
      await Promise.all([reload(), onChanged()])
      onSuccess?.()
      setMessage(`${label} 已删除`)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '删除失败') }
    finally { setBusy(false) }
  }

  async function editMetadata(moldId: number) {
    setBusy(true); setError('')
    try { setEditingMold(await api<LiveMold>(`/molds/${moldId}`)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '模具资料读取失败') }
    finally { setBusy(false) }
  }

  const shelves = locations.filter((item) => item.active && item.type === 'SHELF')
  const existingSet = sets.find((item) => item.model_code.toUpperCase() === moldNumber.trim().toUpperCase() && item.mold_category === category)
  let plannedSizes: string[] = []
  try { plannedSizes = parseSizeList(sizeText) } catch { /* Validation is shown on submit. */ }
  const managedLocations = locations.filter((item) => item.type !== 'LINE' || item.active)
  const visibleLocations = managedLocations.filter((item) => `${item.code} ${item.name} ${locationTypeNames[item.type] ?? item.type}`.toLowerCase().includes(locationQuery.trim().toLowerCase()))
  const visibleMolds = molds.filter((item) => `${moldName(item)} ${item.code}`.toLowerCase().includes(moldQuery.trim().toLowerCase()))
  function clearLocationSelections(locationId: number) {
    for (const clear of [setDefaultLocationId, setNewDefaultId]) clear((current) => current === String(locationId) ? '' : current)
  }
  const locationOptions = <><option value="">选择库位</option>{shelves.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.name}</option>)}</>
  const shelfZone = zone.trim().toUpperCase()
  const shelfRack = rack.trim()
  const shelfLevel = level.trim()
  const shelfPreview = shelfZone && /^[\p{L}\p{N}]+$/u.test(shelfZone) && /^\d+$/.test(shelfRack) && /^\d+$/.test(shelfLevel) && Number(shelfRack) > 0 && Number(shelfLevel) > 0
    ? `${shelfZone}-${String(Number(shelfRack)).padStart(2, '0')}-${Number(shelfLevel)}`
    : ''

  return <div className="live-management">
    {error && <p className="live-error" role="alert">{error}</p>}{message && <p className="live-note" role="status">{message}</p>}
    {loading && !people.length && !models.length && <LoadingSkeleton />}
    {user.role !== 'ADMIN' && <p className="live-note">只有系统维护员可以修改基础资料。</p>}
    {user.role === 'ADMIN' && <div className="management-grid">
      <form className="card management-card management-mold-create" onSubmit={(event) => { event.preventDefault(); void generate() }}>
        <h2>模具建档与生成</h2><p>款号区分款式，A模/B模区分同款的两套，码数区分套内模具。</p>
        <div className="management-generation-modes" role="group" aria-label="生成方式">{(['SET', 'SINGLE'] as const).map((mode) => <button type="button" key={mode} className={generationMode === mode ? 'primary-button' : 'secondary-button'} aria-pressed={generationMode === mode} disabled={busy} onClick={() => setGenerationMode(mode)}>{mode === 'SET' ? '整套生成' : '单个生成'}</button>)}</div>
        <div className="management-inline"><label>鞋类<select value={shoeType} onChange={(event) => chooseType(event.target.value as ShoeType)} disabled={busy || !!models.find((item) => item.code.toUpperCase() === moldNumber.trim().toUpperCase())?.shoe_type}>{shoeTypes.map((type) => <option key={type}>{type}</option>)}</select></label><label>模具编号（款号）<input list="existing-mold-numbers" value={moldNumber} onChange={(event) => chooseIdentity(event.target.value, category)} required maxLength={73} placeholder="例如：QD-264301" /></label><label>模具类别<select value={category} onChange={(event) => chooseIdentity(moldNumber, event.target.value)}><option>A模</option><option>B模</option></select></label></div>
        <datalist id="existing-mold-numbers">{models.map((item) => <option value={item.code} key={item.id} />)}</datalist>
        {(shoeType === '男童' || shoeType === '女童') && !existingSet && <div className="management-generation-modes"><button type="button" className="secondary-button" onClick={() => { setSizeText(bigKidsSizes.join('、')); setSingleSize('') }}>使用大童十码</button><button type="button" className="secondary-button" onClick={() => { setSizeText(littleKidsSizes.join('、')); setSingleSize('') }}>使用小童十码</button></div>}
        <label>整套码数清单<input value={sizeText} readOnly={!!existingSet} onChange={(event) => { setSizeText(event.target.value); setSingleSize('') }} required placeholder="用顿号或逗号分隔，例如：39、40、40.5" /></label>
        <p>{existingSet ? `该套已建档 ${existingSet.size_count}/${existingSet.expected_size_count ?? 10} 个码数，使用原有清单。整套生成只补齐缺少的码数。` : `默认码段供参考，可按实际模具调整；当前清单 ${plannedSizes.length} 个码数。男童与女童共用尺码模板。`}</p>
        {generationMode === 'SINGLE' && <label>本次生成码数<select value={singleSize} onChange={(event) => setSingleSize(event.target.value)} required><option value="">选择一个码数</option>{plannedSizes.map((size) => { const exists = molds.some((item) => item.set_code === existingSet?.code && item.size_label === size); return <option value={size} key={size} disabled={exists}>{size}#{exists ? ' · 已建档' : ''}</option> })}</select></label>}
        <label>初始库位（仅新增码数）<select value={defaultLocationId} onChange={(event) => setDefaultLocationId(event.target.value)} required>{locationOptions}</select></label>
        <div className="management-label-fields"><MoldMetadataFields value={newMetadata} onChange={setNewMetadata} /></div>
        <p>标签资料应用到本次新增模具。库位最多存放 10 个模具；已有模具及该套默认库位保持原值。</p><button className="primary-button" disabled={busy || !plannedSizes.length}>{generationMode === 'SINGLE' ? '生成单个模具' : `生成整套 · ${plannedSizes.length} 个码数`}</button>
      </form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/people', { name: personName, employee_code: employeeCode || null }, '人员已新增') }}><h2>新增人员</h2><label>姓名<input value={personName} onChange={(event) => setPersonName(event.target.value)} required /></label><label>员工编号（可选）<input value={employeeCode} onChange={(event) => setEmployeeCode(event.target.value)} /></label><button className="primary-button" disabled={busy}>保存人员</button></form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit('/locations', locationType === 'SHELF' ? { type: locationType, zone, rack, level } : { code: locationCode, name: locationName, type: locationType }, '位置已新增') }}>
        <h2>新增位置</h2>
        <label>类型<select value={locationType} onChange={(event) => setLocationType(event.target.value)}><option value="SHELF">普通库位</option><option value="LINE">产线</option><option value="INSPECTION">待检区</option><option value="REPAIR">维修区</option><option value="SCRAP">报废区</option><option value="UNKNOWN">未知位置</option></select></label>
        {locationType === 'SHELF' ? <>
          <div className="management-inline"><label>区域<input value={zone} onChange={(event) => setZone(event.target.value)} required maxLength={20} /></label><label>货架<input value={rack} onChange={(event) => setRack(event.target.value)} required inputMode="numeric" pattern="[0-9]+" /></label><label>层<input value={level} onChange={(event) => setLevel(event.target.value)} required inputMode="numeric" pattern="[0-9]+" /></label></div>
          {shelfPreview && <p>将生成库位编号 {shelfPreview}</p>}
        </> : <>
          <label>编号<input value={locationCode} onChange={(event) => setLocationCode(event.target.value)} required /></label>
          <label>名称<input value={locationName} onChange={(event) => setLocationName(event.target.value)} required /></label>
        </>}
        <button className="primary-button" disabled={busy}>保存位置</button>
      </form>
      <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void submit(`/sets/${defaultSetId}/default-location`, { location_id: Number(newDefaultId), reason }, '默认库位已修改；实物位置未改变', 'PATCH') }}><h2>调整默认库位</h2><label>模具套<select value={defaultSetId} onChange={(event) => setDefaultSetId(event.target.value)} required><option value="">选择模具套</option>{sets.map((item) => <option value={item.id} key={item.id}>{setName(item)} · 当前 {item.default_location}</option>)}</select></label><label>新默认库位<select value={newDefaultId} onChange={(event) => setNewDefaultId(event.target.value)} required>{locationOptions}</select></label><label>原因<input value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} required /></label><p>此操作只改变归还提示，不代表实物已搬动。</p><button className="primary-button" disabled={busy}>确认调整</button></form>
    </div>}
    <section className="card management-list">
      <h2>现有资料</h2><p>人员 {people.length} · 位置 {managedLocations.length} · 款式 {models.length} · 模具套 {sets.length} · 单模具 {molds.length}</p>
    </section>
    <section className="card management-list">
      <h2>位置管理</h2><p>产线均可删除，历史流转记录会保留。其他位置仅在尚未被业务使用时可删除。</p>
      <input className="management-search" aria-label="搜索位置" placeholder="搜索位置编号或名称" value={locationQuery} onChange={(event) => setLocationQuery(event.target.value)} />
      <div className="management-set-list">{visibleLocations.map((location) => <div key={location.id}><strong>{location.code}</strong><span>{location.name} · {locationTypeNames[location.type] ?? location.type}{location.active ? '' : ' · 已停用'}</span>{user.role === 'ADMIN' && <button className="management-delete" type="button" disabled={busy} onClick={() => void remove(`/locations/${location.id}`, `${locationTypeNames[location.type] ?? '位置'} ${location.code}`, () => clearLocationSelections(location.id), location.type === 'LINE' ? `确定删除产线 ${location.code}？历史流转记录会保留，仍在该产线的模具可继续归还或转出。` : undefined)}>删除</button>}</div>)}{!visibleLocations.length && !loading && <EmptyState>没有匹配的位置</EmptyState>}</div>
    </section>
    <section className="card management-list">
      <h2>模具套别</h2><div className="management-set-list">{sets.map((item) => <div key={item.id}><strong>{setName(item)}</strong><span>{item.size_count}/{item.expected_size_count ?? 10} 个码数 · 默认库位 {item.default_location} {item.complete ? '' : '· 档案未完整'}{!item.mold_category ? ` · 历史档案 ${item.code}` : ''}</span>{user.role === 'ADMIN' && item.size_count === 0 && <button className="management-delete" type="button" disabled={busy} onClick={() => void remove(`/sets/${item.id}`, setName(item), () => setDefaultSetId((current) => current === String(item.id) ? '' : current))}>删除空档案</button>}</div>)}{!sets.length && !loading && <EmptyState>暂无模具资料，可在上方整套或单个生成</EmptyState>}</div>
    </section>
    {user.role === 'ADMIN' && editingMold && <MoldMetadataEditor key={`${editingMold.id}-${editingMold.version}`} mold={editingMold} onCancel={() => setEditingMold(null)} onSaved={async () => { await Promise.all([reload(), onChanged()]); setEditingMold(null); setMessage('标签资料已保存，请重新生成标签预览') }} />}
    <section className="card management-list">
      <h2>单模具</h2><p>可删除单个生成或整套生成中尚未使用的模具；已有流转、盘点、打印记录或正在盘点时不能删除。</p><input className="management-search" aria-label="搜索单模具" placeholder="搜索款号、类别或码数" value={moldQuery} onChange={(event) => setMoldQuery(event.target.value)} /><div className="management-set-list">{visibleMolds.map((item) => <div key={item.id}><strong>{moldName(item)}</strong><span>{item.current_location}</span>{user.role === 'ADMIN' && <div className="management-row-actions"><button type="button" disabled={busy} onClick={() => void editMetadata(item.id)}>编辑标签资料</button><button className="management-delete" type="button" disabled={busy} onClick={() => void remove(`/molds/${item.id}`, `模具 ${moldName(item)}`, () => setEditingMold((current) => current?.id === item.id ? null : current), `确定删除模具 ${moldName(item)}？仅删除这个码数，其余模具和整套码数清单保留。删除后不能撤销。`)}>删除模具</button></div>}</div>)}{!visibleMolds.length && !loading && <EmptyState>没有匹配的单模具</EmptyState>}</div>
    </section>
    <section className="card management-list"><h2>人员</h2>{user.role === 'ADMIN' && <label className="management-reason">停用或启用原因<input value={personReason} onChange={(event) => setPersonReason(event.target.value)} minLength={3} /></label>}<div className="management-set-list">{people.map((person) => <div key={person.id}><strong>{person.name}</strong><span>{person.employee_code ?? '无员工编号'} · {person.active ? '启用' : '停用'}</span>{user.role === 'ADMIN' && <div className="management-row-actions"><button type="button" disabled={busy || person.name === user.person} onClick={() => { if (personReason.trim().length < 3) { setError('请先填写至少 3 个字的处理原因'); return } void submit(`/people/${person.id}/active`, { active: !person.active, reason: personReason }, person.active ? '人员已停用' : '人员已启用', 'PATCH') }}>{person.active ? '停用' : '启用'}</button><button className="management-delete" type="button" disabled={busy} onClick={() => void remove(`/people/${person.id}`, `人员 ${person.name}`)}>删除</button></div>}</div>)}</div></section>
  </div>
}
