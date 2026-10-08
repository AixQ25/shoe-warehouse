import { useState } from 'react'
import { api, csrfToken } from './liveApi'
import type { SessionUser } from './liveApi'
import { DataTable } from './WarehouseUI'
import './LiveDataPage.css'

interface ImportError { row: number; field: string; message: string }
interface Preview { valid: boolean; token?: string; sha256?: string; row_count: number; model_count?: number; set_count?: number; expires_at?: string; errors: ImportError[]; filename?: string }
interface CommitResult { batch_id: number; token: string; model_count: number; set_count: number; mold_count: number; operation_ids: number[] }

function savedPreview(userId: number): Preview | null {
  try {
    const stored = JSON.parse(localStorage.getItem(`warehouse-import-preview-${userId}`) ?? 'null') as Preview | null
    return stored?.valid && stored.token && stored.sha256 ? stored : null
  } catch { return null }
}

function rememberPreview(userId: number, preview: Preview | null) {
  try {
    const key = `warehouse-import-preview-${userId}`
    if (preview) localStorage.setItem(key, JSON.stringify(preview))
    else localStorage.removeItem(key)
  } catch { /* 当前页仍可继续确认导入。 */ }
}

export default function LiveDataPage({ user, onChanged }: { user: SessionUser; onChanged: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Preview | null>(() => savedPreview(user.id))
  const [committed, setCommitted] = useState<CommitResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  async function download(path: string, filename: string) {
    setBusy(true)
    setNotice('')
    try {
      const response = await fetch(`/api${path}`, { credentials: 'same-origin' })
      if (!response.ok) throw new Error(`下载失败（${response.status}）`)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : '下载失败') }
    finally { setBusy(false) }
  }

  async function previewFile() {
    if (!file) { setNotice('请先选择 CSV 文件'); return }
    setBusy(true)
    setNotice('')
    try {
      const result = await api<Preview>('/imports/preview', { method: 'POST', headers: { 'Content-Type': 'text/csv; charset=utf-8', 'X-CSRF-Token': csrfToken() }, body: file })
      result.filename = file.name
      setPreview(result)
      if (result.valid) {
        rememberPreview(user.id, result)
        setNotice('预览通过；请核对数量后确认导入。预览 30 分钟内有效。')
      } else {
        rememberPreview(user.id, null)
        setNotice(`发现 ${result.errors.length} 项问题，尚未写入数据库。`)
      }
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : '预览失败') }
    finally { setBusy(false) }
  }

  async function commit() {
    if (!preview?.valid || !preview.token || !preview.sha256) return
    setBusy(true)
    setNotice('')
    try {
      const result = await api<CommitResult>('/imports/commit', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ token: preview.token, sha256: preview.sha256 }) })
      setCommitted(result)
      setPreview(null)
      setFile(null)
      rememberPreview(user.id, null)
      setNotice(`导入成功：${result.set_count} 套、${result.mold_count} 个模具；生成 ${result.operation_ids.length} 张初始化单据。`)
      await onChanged()
    } catch (cause) { setNotice(`${cause instanceof Error ? cause.message : '提交失败'}；请保留预览记录，查明结果后再重试。`) }
    finally { setBusy(false) }
  }

  return <div className="live-data-page">
    <section className="card live-data-card"><h3>导出</h3><p>库存导出包含当前有效模具；流水导出包含操作时间、人员和逐件前后状态。领用账号只能导出自己的流水。</p><div className="live-data-actions"><button className="secondary-button" type="button" disabled={busy} onClick={() => void download('/exports/inventory', 'warehouse-inventory.csv')}>下载库存 CSV</button><button className="secondary-button" type="button" disabled={busy} onClick={() => void download('/exports/operations', 'warehouse-operations.csv')}>下载流水 CSV</button></div></section>
    {user.role === 'ADMIN' && <section className="card live-data-card"><h3>批量初始建档</h3><p>先维护真实库位，再按模板填写。每款按 A模/B模建套，选择男鞋、女鞋、男童或女童，按该套码数清单填写完整；单件身份自动生成；导入不会覆盖已有模具。</p><div className="live-data-actions"><button className="secondary-button" type="button" disabled={busy} onClick={() => void download('/imports/template', 'mold-import-template.csv')}>下载空白模板</button></div><label className="live-data-file">选择 UTF-8 CSV 文件<input type="file" accept=".csv,text/csv" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); setCommitted(null); setNotice(''); rememberPreview(user.id, null) }} /></label><button className="primary-button" type="button" disabled={busy || !file} onClick={() => void previewFile()}>预览并校验</button>
      {preview?.valid && <div className="live-data-preview"><strong>{preview.filename ?? '已保存的预览'} · 校验通过</strong><span>{preview.model_count} 个款式 · {preview.set_count} 套 · {preview.row_count} 个模具</span><p>确认后整批写入，并为每套生成初始化流水。提交超时可使用本次预览重试。</p><button className="primary-button" type="button" disabled={busy} onClick={() => void commit()}>确认导入</button></div>}
      {preview && !preview.valid && <div className="live-data-errors"><strong>逐行错误</strong><DataTable rows={preview.errors} rowKey={(item) => `${item.row}-${item.field}-${item.message}`} empty="没有逐行错误" columns={[{ key: 'row', title: 'CSV 行号', render: (item) => item.row }, { key: 'field', title: '字段', render: (item) => item.field }, { key: 'message', title: '原因', render: (item) => item.message }]} /></div>}
      {committed && <p className="live-data-result">批次 {committed.batch_id} 已导入；页面数据已刷新。</p>}
    </section>}
    {user.role === 'ADMIN' && <p>shoe_type 填鞋类，set_sizes 可填自定义清单（顿号分隔），留空使用该类默认十码。模板另含厂家、类别、排模双数、材质、季度和开制日期六列。排模双数填 1～99，季度如 26Q4，日期如 2026-03-16；旧模板仍可导入，已有模具可在基础资料中补录。</p>}
    {notice && <div className="live-work-notice" role="status">{notice}</div>}
  </div>
}
