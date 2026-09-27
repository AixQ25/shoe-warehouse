import type { ReactNode } from 'react'
import { stateNames } from './liveApi'
import './WarehouseUI.css'

export function EmptyState({ children }: { children: ReactNode }) { return <div className="warehouse-empty" role="status">{children}</div> }

export function LoadingSkeleton({ rows = 4 }: { rows?: number }) { return <div className="warehouse-skeleton" aria-label="正在加载" role="status">{Array.from({ length: rows }, (_, index) => <span key={index} />)}</div> }

export function StatusBadge({ status, label }: { status: string; label?: string }) { return <span className={`warehouse-status warehouse-status-${status.toLowerCase().replace(/[^a-z_]/g, '')}`}>{label ?? stateNames[status] ?? status}</span> }

export interface TableColumn<Row> { key: string; title: string; render: (row: Row) => ReactNode; className?: string }
export function DataTable<Row>({ columns, rows, rowKey, empty, note }: { columns: TableColumn<Row>[]; rows: Row[]; rowKey: (row: Row) => string | number; empty: string; note?: ReactNode }) {
  return <div className="card table-wrap warehouse-table"><table><thead><tr>{columns.map((column) => <th className={column.className} key={column.key}>{column.title}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={rowKey(row)}>{columns.map((column) => <td className={column.className} key={column.key}>{column.render(row)}</td>)}</tr>)}</tbody></table>{rows.length === 0 && <EmptyState>{empty}</EmptyState>}{note && <p className="table-note">{note}</p>}</div>
}

export function Drawer({ title, subtitle, onClose, children, className = '' }: { title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode; className?: string }) {
  return <div className="drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><aside className={`drawer ${className}`} role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : '详情'}><div className="drawer-top"><div>{subtitle && <p className="eyebrow">{subtitle}</p>}<h2>{title}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭">×</button></div>{children}</aside></div>
}
