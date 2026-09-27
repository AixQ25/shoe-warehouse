import { useEffect, useState } from 'react'
import LiveWarehousePage from './LiveWarehousePage'
import MobileApp from './MobileApp'
import type { LiveTab } from './LiveWarehousePage'
import './App.css'

const navigation: { id: LiveTab; label: string; icon: string }[] = [
  { id: 'map', label: '仓库布局', icon: '▦' },
  { id: 'molds', label: '模具查询', icon: '⌕' },
  { id: 'sets', label: '按套矩阵', icon: '▧' },
  { id: 'overview', label: '仓库概况', icon: '◫' },
  { id: 'lines', label: '产线视图', icon: '⇄' },
  { id: 'records', label: '流转记录', icon: '▤' },
  { id: 'tools', label: '仓库工具', icon: '☷' },
  { id: 'master', label: '基础资料', icon: '▧' },
  { id: 'admin', label: '系统管理', icon: '⚙' },
]

function initialTab(): LiveTab {
  const requested = new URLSearchParams(window.location.search).get('page')
  if (requested === 'work' || requested === 'stocktake' || requested === 'data' || requested === 'labels') return requested
  return navigation.find((item) => item.id === requested)?.id ?? 'map'
}

export default function App() {
  const [tab, setTab] = useState<LiveTab>(initialTab)
  const [mobileWidth, setMobileWidth] = useState(() => window.matchMedia('(max-width: 720px)').matches)
  const mobileView = mobileWidth || /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || new URLSearchParams(window.location.search).get('view') === 'mobile'
  useEffect(() => {
    const media = window.matchMedia('(max-width: 720px)')
    const update = () => setMobileWidth(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    if (mobileView) return
    const url = new URL(window.location.href)
    url.searchParams.set('page', tab)
    url.searchParams.delete('source')
    url.searchParams.delete('demo')
    window.history.replaceState(null, '', url)
  }, [mobileView, tab])

  if (mobileView) return <MobileApp />

  return <div className="app-shell">
    <aside className="sidebar">
      <button className="sidebar-brand" type="button" onClick={() => setTab('map')}><span className="brand-mark">▦</span><span>鞋模具仓库</span></button>
      <nav className="sidebar-nav" aria-label="主导航">{navigation.map((item) => <button type="button" key={item.id} className={tab === item.id || (tab === 'work' && item.id === 'records') || (['stocktake', 'data', 'labels'].includes(tab) && item.id === 'tools') ? 'active' : ''} onClick={() => setTab(item.id)}><span aria-hidden="true">{item.icon}</span>{item.label}</button>)}</nav>
    </aside>
    <div className="app-main"><main><LiveWarehousePage tab={tab} onTabChange={setTab} /></main></div>
  </div>
}
