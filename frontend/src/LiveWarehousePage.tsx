import { newRequestId } from './requestId'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, csrfToken, kindNames, localTime, sessionExpired } from './liveApi'
import type { DashboardSummary, LineSummary, LiveMold, LiveOperation, Location, MoldPage, SessionUser, SetSummary } from './liveApi'
import LiveWorkPage from './LiveWorkPage'
import LiveStocktakePage from './LiveStocktakePage'
import LiveMoldActions from './LiveMoldActions'
import LiveDataPage from './LiveDataPage'
import LiveLabelsPage from './LiveLabelsPage'
import LiveMasterPage from './LiveMasterPage'
import LiveAdminPage from './LiveAdminPage'
import WarehouseTools from './WarehouseTools'
import { DataTable, Drawer, EmptyState, LoadingSkeleton, StatusBadge } from './WarehouseUI'
import './LiveWarehousePage.css'

export type LiveTab = 'map' | 'molds' | 'sets' | 'overview' | 'lines' | 'records' | 'work' | 'tools' | 'stocktake' | 'data' | 'labels' | 'master' | 'admin'

export default function LiveWarehousePage({ tab, onTabChange }: { tab: LiveTab; onTabChange: (tab: LiveTab) => void }) {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [checking, setChecking] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [locations, setLocations] = useState<Location[]>([])
  const [molds, setMolds] = useState<LiveMold[]>([])
  const [operations, setOperations] = useState<LiveOperation[]>([])
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [sets, setSets] = useState<SetSummary[]>([])
  const [lines, setLines] = useState<LineSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState('')
  const [zone, setZone] = useState('')
  const [selectedLocation, setSelectedLocation] = useState<number | null>(null)
  const [selectedMoldId, setSelectedMoldId] = useState<number | null>(null)
  const [selectedOperationId, setSelectedOperationId] = useState<number | null>(null)
  const [correctionReason, setCorrectionReason] = useState('')
  const [correctionRequestId, setCorrectionRequestId] = useState(() => newRequestId())
  const [correctionNotice, setCorrectionNotice] = useState('')
  const [correcting, setCorrecting] = useState(false)
  const [query, setQuery] = useState('')
  const [recordQuery, setRecordQuery] = useState('')
  const [recordType, setRecordType] = useState('')
  useEffect(() => {
    const expired = () => { setUser(null); setError('登录已失效，请重新登录；待确认请求已保留') }
    window.addEventListener('warehouse-session-expired', expired)
    return () => window.removeEventListener('warehouse-session-expired', expired)
  }, [])
  const refresh = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError('')
    try {
      const [loadedLocations, first, loadedOperations, loadedDashboard, loadedSets, loadedLines] = await Promise.all([
        api<Location[]>('/locations'),
        api<MoldPage>('/molds?offset=0&limit=100'),
        api<LiveOperation[]>('/operations?limit=100'),
        api<DashboardSummary>('/dashboard'),
        api<SetSummary[]>('/set-matrix'),
        api<LineSummary[]>('/production-lines/summary'),
      ])
      const pages = Math.ceil(first.total / 100)
      const rest = await Promise.all(Array.from({ length: Math.max(0, pages - 1) }, (_, index) => api<MoldPage>(`/molds?offset=${(index + 1) * 100}&limit=100`)))
      setLocations(loadedLocations)
      setMolds([ ...first.items, ...rest.flatMap((page) => page.items) ])
      setOperations(loadedOperations)
      setDashboard(loadedDashboard)
      setSets(loadedSets)
      setLines(loadedLines)
      setUpdatedAt(new Date().toISOString())
      setZone((current) => current || loadedLocations.find((location) => location.type === 'SHELF' && location.active && location.zone)?.zone || '')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '数据读取失败')
    } finally {
      if (showLoading) setLoading(false)
    }
  }, [])

  useEffect(() => {
    let alive = true
    api<SessionUser>('/auth/me').then((value) => {
      if (!alive) return
      setUser(value)
      void refresh()
    }).catch((cause) => { if (alive && cause instanceof Error && !cause.message.includes('请先登录')) setError(cause.message) }).finally(() => { if (alive) setChecking(false) })
    return () => { alive = false }
  }, [refresh])

  useEffect(() => {
    if (user?.role === 'READONLY' && ['work', 'data', 'labels'].includes(tab)) onTabChange('map')
  }, [onTabChange, tab, user?.role])

  useEffect(() => {
    if (!user) return
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(false) }, 10_000)
    return () => window.clearInterval(timer)
  }, [refresh, user])

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    try {
      const result = await api<SessionUser>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
      setUser(result)
      if (result.role === 'READONLY' && ['work', 'data', 'labels'].includes(tab)) onTabChange('map')
      setPassword('')
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '登录失败')
    }
  }

  async function logout() {
    try {
      await api('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() } })
    } catch (cause) {
      if (!sessionExpired(cause)) { setError(cause instanceof Error ? cause.message : '退出失败'); return }
    }
    setUser(null)
    setLocations([])
    setMolds([])
    setOperations([])
    setDashboard(null)
    setSets([])
    setLines([])
  }

  function openOperation(id: number) {
    setSelectedOperationId(id)
    setCorrectionReason('')
    setCorrectionNotice('')
    setCorrectionRequestId(newRequestId())
  }

  async function correctOperation(id: number) {
    if (correctionReason.trim().length < 3) { setCorrectionNotice('请填写至少 3 个字的更正原因'); return }
    setCorrecting(true)
    setCorrectionNotice('')
    try {
      const corrected = await api<LiveOperation>(`/operations/${id}/corrections`, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ request_id: correctionRequestId, reason: correctionReason.trim() }) })
      setCorrectionNotice(`已生成补偿更正单 #${corrected.id}`)
      await refresh()
    } catch (cause) {
      setCorrectionNotice(cause instanceof Error ? cause.message : '更正失败，请核对单据')
    } finally { setCorrecting(false) }
  }

  const shelves = useMemo(() => locations.filter((item) => item.type === 'SHELF' && item.active && item.zone && item.rack && item.level), [locations])
  const zones = useMemo(() => [...new Set(shelves.map((item) => item.zone!))].sort(), [shelves])
  const racks = useMemo(() => [...new Set(shelves.filter((item) => item.zone === zone).map((item) => item.rack!))].sort((a, b) => Number(a) - Number(b)), [shelves, zone])
  const byLocation = useMemo(() => {
    const grouped = new Map<number, LiveMold[]>()
    for (const mold of molds) {
      const group = grouped.get(mold.current_location_id) ?? []
      group.push(mold)
      grouped.set(mold.current_location_id, group)
    }
    return grouped
  }, [molds])
  const byDefaultLocation = useMemo(() => {
    const grouped = new Map<number, LiveMold[]>()
    for (const mold of molds) {
      const group = grouped.get(mold.default_location_id) ?? []
      group.push(mold)
      grouped.set(mold.default_location_id, group)
    }
    return grouped
  }, [molds])
  const needle = query.trim().toLowerCase()
  const filtered = useMemo(() => needle ? molds.filter((item) => `${item.code} ${item.model_code} ${item.set_code} ${item.size_label}`.toLowerCase().includes(needle)) : molds, [molds, needle])
  const matchedLocationIds = useMemo(() => new Set(filtered.map((item) => shelves.some((shelf) => shelf.id === item.current_location_id) ? item.current_location_id : shelves.find((shelf) => shelf.code === item.default_location)?.id).filter((id): id is number => id !== undefined)), [filtered, shelves])
  function locateFirst() {
    const first = filtered[0]
    if (!first || !needle) { setSelectedLocation(null); return }
    const shelf = shelves.find((item) => item.id === first.current_location_id) ?? shelves.find((item) => item.code === first.default_location)
    if (shelf) { setZone(shelf.zone ?? ''); setSelectedLocation(shelf.id) }
  }
  const selected = locations.find((item) => item.id === selectedLocation)
  const selectedMolds = selectedLocation ? byLocation.get(selectedLocation) ?? [] : []
  const selectedMold = molds.find((item) => item.id === selectedMoldId)
  const selectedOperation = operations.find((item) => item.id === selectedOperationId)
  const visibleOperations = operations.filter((item) => {
    const needle = recordQuery.trim().toLowerCase()
    return (!recordType || item.type === recordType) && (!needle || `${item.id} ${item.request_id} ${item.created_at} ${localTime(item.created_at)} ${item.actor_name} ${item.items.map((part) => part.mold_code).join(' ')} ${item.items.map((part) => molds.find((mold) => mold.code === part.mold_code)?.set_code ?? '').join(' ')}`.toLowerCase().includes(needle))
  })

  if (checking) return <div className="page-content live-page"><LoadingSkeleton rows={5} /></div>
  if (!user) return <div className="page-content live-page"><div className="live-login card"><h1>登录鞋模具仓库</h1><p>使用本机已创建的账号登录。</p><form onSubmit={login}><label>账号<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label><button className="primary-button" type="submit">登录</button></form>{error && <p className="live-error" role="alert">{error}</p>}</div></div>

  return <div className={`page-content live-page${tab === 'map' ? ' warehouse-map-page' : ''}`}>
    <div className="page-heading"><div><h1>{({ map: '仓库布局', molds: '模具查询', sets: '按套矩阵', overview: '仓库概况', lines: '产线视图', records: '流转记录', work: '流转登记', tools: '仓库工具', stocktake: '库位盘点', data: '批量建档与导出', labels: '标签打印', master: '基础资料', admin: '系统管理' } satisfies Record<LiveTab, string>)[tab]}</h1></div><div className="live-actions">{tab === 'work' && <button className="text-button" type="button" onClick={() => onTabChange('records')}>返回流转记录</button>}{['stocktake', 'data', 'labels'].includes(tab) && <button className="text-button" type="button" onClick={() => onTabChange('tools')}>返回仓库工具</button>}<span>{user.person ?? user.username} · {user.role === 'READONLY' ? '只读' : user.role === 'ADMIN' ? '维护员' : '领用人员'}</span><button className="secondary-button" type="button" onClick={() => void refresh()} disabled={loading}>刷新</button><button className="secondary-button" type="button" onClick={() => void logout()}>退出</button></div></div>
    {updatedAt && <p className="live-note">上次更新：{localTime(updatedAt)} · 每 10 秒自动刷新</p>}
    {error && <div className="live-error" role="alert">{error}；当前仍显示上次成功读取的数据。</div>}
    {loading && !molds.length && <LoadingSkeleton rows={6} />}
    {loading && molds.length > 0 && <p className="live-loading" role="status">正在刷新数据…</p>}
    {tab === 'tools' && <WarehouseTools role={user.role} onSelect={onTabChange} />}
    {tab === 'stocktake' && <p className="live-note">逐库位核对账面与实物；盘点期间该库位暂停流转，差异经核查后处理。</p>}
    {tab === 'data' && <p className="live-note">下载库存和流转记录；维护员可使用 CSV 模板批量建立初始档案。</p>}
    {tab === 'labels' && <p className="live-note">为模具或库位生成二维码标签，预览后可打印或补打。</p>}
    {tab === 'overview' && dashboard && <div className="metric-grid"><div className="card metric"><span>有效模具</span><strong>{dashboard.total_molds}</strong><small>{dashboard.total_sets} 套</small></div><div className="card metric"><span>在库可用</span><strong>{dashboard.ready_molds}</strong></div><div className="card metric"><span>产线使用</span><strong>{dashboard.in_use_molds}</strong></div><div className="card metric"><span>异常 / 待检</span><strong>{dashboard.exception_molds}</strong></div><div className="card metric"><span>可整套领用</span><strong>{dashboard.ready_sets}</strong><small>共 {dashboard.total_sets} 套</small></div></div>}
    {(tab === 'map' || tab === 'molds' || tab === 'sets') && <div className="live-controls"><input aria-label="查询模具" placeholder="搜索套号、型号或模具编号" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && tab === 'map') locateFirst() }} />{tab === 'map' && <button className="secondary-button" type="button" onClick={locateFirst}>定位</button>}</div>}
    {tab === 'map' && needle && <p className="live-note">{filtered.length ? `找到 ${filtered.length} 个模具，涉及 ${matchedLocationIds.size} 个库位` : '没有找到匹配的模具'}</p>}
    {tab === 'work' && user.role !== 'READONLY' && <LiveWorkPage user={user} molds={molds} locations={locations} onChanged={refresh} />}
    {tab === 'stocktake' && <LiveStocktakePage user={user} locations={locations} onChanged={refresh} />}
    {tab === 'data' && user.role !== 'READONLY' && <LiveDataPage user={user} onChanged={refresh} />}
    {tab === 'labels' && user.role !== 'READONLY' && <LiveLabelsPage molds={molds} locations={locations} />}
    {tab === 'master' && <LiveMasterPage user={user} locations={locations} molds={molds} onChanged={refresh} />}
    {tab === 'admin' && <LiveAdminPage user={user} />}
    {user.role === 'READONLY' && (tab === 'work' || tab === 'data' || tab === 'labels') && <div className="card live-restricted"><EmptyState>只读账号不能使用此功能。请由本人使用已授权的作业账号登录。</EmptyState></div>}
    {tab === 'map' && <div className="map-workspace"><aside className="zone-overview"><div className="zone-overview-head">全仓区域</div><div className="zone-list">{zones.map((item) => <button type="button" className={`zone-choice ${zone === item ? 'active' : ''}`} key={item} onClick={() => { setZone(item); setSelectedLocation(null) }}><strong>{item}</strong><span className="zone-rack-count">{new Set(shelves.filter((shelf) => shelf.zone === item).map((shelf) => shelf.rack)).size} 架</span></button>)}</div></aside><section className="rack-panel"><div className="rack-panel-head"><h2>{zone} 区货架</h2><span>点击层位查看当前模具</span></div><div className="rack-strip" style={{ '--rack-columns': Math.max(1, Math.min(racks.length, 10)) } as React.CSSProperties}>{racks.map((rack) => <section className="rack" key={rack}><div className="rack-heading">{zone}-{rack.padStart(2, '0')}</div>{shelves.filter((item) => item.zone === zone && item.rack === rack).sort((a, b) => Number(b.level) - Number(a.level)).map((shelf) => { const expected = byDefaultLocation.get(shelf.id) ?? []; const contents = byLocation.get(shelf.id) ?? []; const representative = expected[0] ?? contents[0]; const count = contents.length; const slots = 10; const overCapacity = count > slots; const match = !needle || matchedLocationIds.has(shelf.id); return <button type="button" className={`rack-level ${match ? '' : 'dimmed'} ${needle && match ? 'match' : ''} ${selectedLocation === shelf.id ? 'selected' : ''} ${overCapacity ? 'over-capacity' : ''}`} key={shelf.id} onClick={() => setSelectedLocation(shelf.id)}><span className="rack-level-no">{shelf.level}</span><span className="rack-level-body"><span className="rack-level-title"><strong>{representative?.set_code ?? <span className="rack-empty">空层</span>}</strong><em>{count}/{slots}{overCapacity ? ` · 超出 ${count - slots}` : ''}</em></span><span className="mini-molds" aria-label={`当前位置有 ${count} 个模具，最多 ${slots} 个${overCapacity ? `，超出 ${count - slots} 个` : ''}`}>{Array.from({ length: slots }, (_, index) => <i key={index} className={index < count ? '' : 'absent'} />)}</span></span></button> })}</section>)}</div></section></div>}
    {tab === 'overview' && <div className="overview-grid"><section className="card overview-card"><h2>最近流转</h2>{operations.slice(0, 8).map((item) => <div className="recent-row" key={item.id}><strong>{kindNames[item.type] ?? item.type}</strong><span>{item.actor_name} · {item.items.length} 个</span><small>{localTime(item.created_at)}</small></div>)}{!operations.length && <EmptyState>暂无流转记录</EmptyState>}</section><section className="card overview-card"><h2>异常模具</h2>{molds.filter((item) => !['READY', 'IN_USE'].includes(item.status)).slice(0, 12).map((item) => <button className="live-summary-row live-summary-button" type="button" key={item.id} onClick={() => setSelectedMoldId(item.id)}><strong>{item.code} · {item.set_code}</strong><span><StatusBadge status={item.status} /> · {item.current_location}</span></button>)}{!molds.some((item) => !['READY', 'IN_USE'].includes(item.status)) && <EmptyState>暂无异常模具</EmptyState>}</section></div>}
    {tab === 'sets' && <div className="set-grid">{sets.filter((item) => !needle || `${item.set_code} ${item.model_code} ${item.items.map((mold) => mold.code).join(' ')}`.toLowerCase().includes(needle)).map((item) => <section className="card set-card" key={item.set_id}><div className="set-card-head"><div><strong>{item.set_code}</strong><span>型号 {item.model_code}</span></div><b>{item.complete ? '10 个码数' : `${item.items.length}/10 个码数`}</b></div><div className="set-sizes">{item.items.map((mold) => <button type="button" key={mold.id} className={`set-size status-${mold.status.toLowerCase()}`} onClick={() => setSelectedMoldId(mold.id)} title={`${mold.code} · ${mold.current_location}`}><strong>{mold.size_label}</strong><small>{mold.status === 'READY' ? '在库' : mold.status === 'IN_USE' ? '领用' : '异常'}</small></button>)}</div><p>默认库位 {item.default_location} · 点击尺码查看模具</p></section>)}{!sets.length && <EmptyState>暂无模具套资料</EmptyState>}</div>}
    {tab === 'lines' && <><div className="line-summary">{lines.map((line) => <div className="card line-summary-card" key={line.line_id}><strong>{line.line_code}</strong><span>{line.sets.reduce((count, item) => count + item.mold_count, 0)} 个模具</span></div>)}</div><div className="live-line-list">{lines.map((line) => <section className="card live-line-card" key={line.line_id}><h2>{line.line_code}</h2><p>使用中 {line.sets.reduce((count, item) => count + item.mold_count, 0)} 个模具 · {line.sets.length} 套</p>{line.sets.map((item) => <div className="live-summary-row" key={item.set_code}><strong>{item.set_code}</strong><span>{item.mold_count} 个 · {item.sizes.join('、')} 码</span><span>责任人：{item.custodians.join('、')}</span></div>)}{!line.sets.length && <EmptyState>当前没有领用到此产线的模具</EmptyState>}</section>)}{!lines.length && <EmptyState>暂无产线资料</EmptyState>}</div></>}
    {tab === 'molds' && <DataTable rows={filtered.slice(0, 200)} rowKey={(item) => item.id} empty="没有匹配的模具" note={filtered.length > 200 ? `显示前 200 项，共 ${filtered.length} 项；请缩小查询范围。` : `共 ${filtered.length} 项`} columns={[
      { key: 'code', title: '编号', className: 'mono', render: (item) => item.code },
      { key: 'name', title: '套号 / 型号', render: (item) => <>{item.set_code}<small>{item.model_code}</small></> },
      { key: 'set', title: '套号', render: (item) => item.set_code },
      { key: 'size', title: '尺码', render: (item) => item.size_label },
      { key: 'status', title: '状态', render: (item) => <StatusBadge status={item.status} /> },
      { key: 'location', title: '当前位置', render: (item) => item.current_location },
      { key: 'custodian', title: '责任人', render: (item) => item.custodian ?? '—' },
      { key: 'detail', title: '', render: (item) => <button className="text-button" type="button" onClick={() => setSelectedMoldId(item.id)}>详情</button> },
    ]} />}
    {tab === 'records' && <><div className="filters card"><input aria-label="搜索流转记录" placeholder="搜索单号、日期、人员、套号或模具编号" value={recordQuery} onChange={(event) => setRecordQuery(event.target.value)} /><select aria-label="筛选操作类型" value={recordType} onChange={(event) => setRecordType(event.target.value)}><option value="">全部类型</option>{[...new Set(operations.map((item) => item.type))].map((type) => <option value={type} key={type}>{kindNames[type] ?? type}</option>)}</select><span className="count-badge">{visibleOperations.length} 条记录</span>{user.role !== 'READONLY' && <button className="text-button" type="button" onClick={() => onTabChange('work')}>登记流转</button>}</div><DataTable rows={visibleOperations} rowKey={(item) => item.id} empty="没有匹配的流转记录" note={`显示最近 ${operations.length} 张单据；作业账号只显示本人的记录。`} columns={[
      { key: 'time', title: '时间', className: 'mono', render: (item) => localTime(item.created_at) },
      { key: 'id', title: '单据号', className: 'mono', render: (item) => `#${item.id}` },
      { key: 'type', title: '类型', render: (item) => <StatusBadge status={item.type} label={kindNames[item.type] ?? item.type} /> },
      { key: 'actor', title: '操作人', render: (item) => item.actor_name },
      { key: 'sets', title: '涉及模具套', render: (item) => [...new Set(item.items.map((part) => molds.find((mold) => mold.code === part.mold_code)?.set_code).filter(Boolean))].join('、') || '—' },
      { key: 'count', title: '数量', render: (item) => `${item.items.length} 个` },
      { key: 'destination', title: '去向 / 库位', render: (item) => item.target_location_code },
      { key: 'detail', title: '', render: (item) => <button className="text-button" type="button" onClick={() => openOperation(item.id)}>查看明细</button> },
    ]} /></>}
    {selected && tab === 'map' && <Drawer title={selected.name} subtitle="库位详情" onClose={() => setSelectedLocation(null)}>{selectedMolds.length ? selectedMolds.map((item) => <button className="live-drawer-row" type="button" key={item.id} onClick={() => { setSelectedLocation(null); setSelectedMoldId(item.id) }}><strong>{item.code} · {item.size_label}码</strong><span>{item.set_code} · <StatusBadge status={item.status} /></span></button>) : <EmptyState>这里暂无登记模具</EmptyState>}</Drawer>}
    {selectedMold && <LiveMoldActions mold={selectedMold} locations={locations} user={user} onClose={() => setSelectedMoldId(null)} onChanged={refresh} />}
    {selectedOperation && tab === 'records' && <Drawer title={kindNames[selectedOperation.type] ?? selectedOperation.type} subtitle={`业务单据 #${selectedOperation.id}`} onClose={() => setSelectedOperationId(null)}><p>{localTime(selectedOperation.created_at)} · {selectedOperation.actor_name}</p>{selectedOperation.reason && <p>说明：{selectedOperation.reason}</p>}{selectedOperation.correction_of_operation_id && <p>补偿原单据：#{selectedOperation.correction_of_operation_id}</p>}{selectedOperation.items.map((item) => <div className="live-operation-item" key={item.mold_code}><strong>{item.mold_code}</strong><span><StatusBadge status={item.before_status} /> → <StatusBadge status={item.after_status} /></span><span>{locations.find((location) => location.id === item.before_location_id)?.code ?? '未登记'} → {locations.find((location) => location.id === item.after_location_id)?.code ?? '未知位置'}</span>{item.note && <small>逐件说明：{item.note}</small>}</div>)}{user.role === 'ADMIN' && ['ISSUE', 'RETURN', 'MOVE', 'TRANSFER'].includes(selectedOperation.type) && <div className="operation-correction"><h3>补偿更正</h3>{operations.some((item) => item.correction_of_operation_id === selectedOperation.id) ? <p>这张单据已有补偿更正。</p> : <><p>仅限这张单据的模具没有后续变化、相关库位未盘点冻结时使用。整套完好归还需专项核查。</p><label>更正原因<textarea value={correctionReason} maxLength={300} onChange={(event) => setCorrectionReason(event.target.value)} /></label><button className="primary-button" type="button" disabled={correcting} onClick={() => void correctOperation(selectedOperation.id)}>生成补偿更正单</button></>}{correctionNotice && <p role="status">{correctionNotice}</p>}</div>}</Drawer>}
  </div>
}
