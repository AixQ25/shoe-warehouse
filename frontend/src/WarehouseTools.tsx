import type { LiveTab } from './LiveWarehousePage'
import './WarehouseTools.css'

const tools: { tab: 'stocktake' | 'data' | 'labels'; icon: string; title: string; description: string; detail: string }[] = [
  { tab: 'stocktake', icon: '☷', title: '库位盘点', description: '核对货架上的实物与系统记录。', detail: '按库位扫描、查看漏扫或错位，核查后关闭任务。' },
  { tab: 'data', icon: '⬇', title: '批量建档与导出', description: '用表格交换仓库资料。', detail: '下载库存与流转 CSV；维护员可按模板批量建档。' },
  { tab: 'labels', icon: '▥', title: '标签打印', description: '给模具和库位制作二维码标签。', detail: '按套、按件或按库位预览，支持打印和补打。' },
]

export default function WarehouseTools({ role, onSelect }: { role: string; onSelect: (tab: LiveTab) => void }) {
  return <div className="warehouse-tools-grid">{tools.map((item) => {
    const restricted = role === 'READONLY' && item.tab !== 'stocktake'
    return <section className="card warehouse-tool-card" key={item.tab}>
      <span className="warehouse-tool-icon" aria-hidden="true">{item.icon}</span>
      <h2>{item.title}</h2>
      <p>{item.description}</p>
      <small>{item.detail}</small>
      <button className="secondary-button" type="button" disabled={restricted} onClick={() => onSelect(item.tab)}>{restricted ? '需要作业账号' : '进入'}</button>
    </section>
  })}</div>
}
