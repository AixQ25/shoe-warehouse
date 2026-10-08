export interface SessionUser { id: number; username: string; role: string; person: string | null }
export interface Location { id: number; code: string; name: string; type: string; zone: string | null; rack: string | null; level: string | null; active: boolean }
import type { MoldMetadata } from './moldLabel'

export interface LiveMold extends MoldMetadata { id: number; code: string; mold_number?: string; set_category?: string | null; shoe_type?: string | null; expected_size_count?: number | null; set_code: string; model_code: string; name: string; size_label: string; status: string; version: number; current_location_id: number; current_location: string; default_location_id: number; default_location: string; custodian: string | null }
export interface LiveOperation { id: number; request_id: string; type: string; actor_name: string; target_location_code: string; reason: string | null; correction_of_operation_id?: number | null; created_at: string; items: { mold_code: string; before_status: string; after_status: string; before_location_id: number | null; after_location_id: number; note: string | null }[] }
export interface MoldPage { total: number; items: LiveMold[] }
export interface DashboardSummary { total_molds: number; ready_molds: number; in_use_molds: number; exception_molds: number; ready_sets: number; total_sets: number }
export interface SetSummary { set_id: number; set_code: string; name: string; model_code: string; mold_category?: string | null; shoe_type?: string | null; expected_size_count?: number | null; default_location: string; complete: boolean; items: LiveMold[] }
export interface LineSummary { line_id: number; line_code: string; sets: { set_code: string; model_code?: string; mold_category?: string | null; shoe_type?: string | null; expected_size_count?: number | null; name: string; mold_count: number; sizes: string[]; custodians: string[] }[] }

export const stateNames: Record<string, string> = { NOT_REGISTERED: '未建档', READY: '在库可用', IN_USE: '产线领用', PENDING_INSPECTION: '待检', IN_REPAIR: '维修中', UNVERIFIED: '待核查', SCRAPPED: '已报废' }
export const kindNames: Record<string, string> = { INITIALIZE: '初始建档', ISSUE: '领用', RETURN: '归还', MOVE: '移库', TRANSFER: '转线', CORRECTION: '补偿更正', STOCKTAKE_ADJUST: '盘点调整', RETURN_FOR_INSPECTION: '异常归还待检', SEND_REPAIR: '送修', REPAIR_COMPLETE: '维修完成', INSPECTION_PASS: '检验通过', SCRAP: '报废', FOUND: '核查找回' }

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) { super(message); this.status = status; this.code = code }
}

export function rejectedSubmission(cause: unknown): boolean {
  return cause instanceof ApiError && [400, 404, 409, 422].includes(cause.status) && !['REQUEST_ID_CONFLICT', 'REQUEST_CONFLICT'].includes(cause.code ?? '')
}

export function sessionExpired(cause: unknown): boolean {
  return cause instanceof ApiError && (cause.status === 401 || ['ACCOUNT_DISABLED', 'CSRF_FAILED'].includes(cause.code ?? ''))
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 20_000)
  try {
    let response: Response
    try {
      response = await fetch(`/api${path}`, { credentials: 'same-origin', ...init, signal: init?.signal ?? controller.signal, headers: { 'Content-Type': 'application/json', ...init?.headers } })
    } catch {
      throw new Error(controller.signal.aborted ? '请求超时。库存提交结果可能尚未确认，请查询原请求结果。' : '无法连接仓库服务。请检查网络和电脑服务。')
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null) as { detail?: { message?: string; error_code?: string } } | null
      const fallback = [502, 503, 504].includes(response.status) ? `仓库服务暂时不可用，请稍后重试（${response.status}）` : `请求失败（${response.status}）`
      const error = new ApiError(body?.detail?.message ?? fallback, response.status, body?.detail?.error_code)
      if (sessionExpired(error) && error.code !== 'BAD_CREDENTIALS') window.dispatchEvent(new Event('warehouse-session-expired'))
      throw error
    }
    return await response.json() as T
  } finally { window.clearTimeout(timeout) }
}

export function csrfToken() {
  return document.cookie.split('; ').find((part) => part.startsWith('warehouse_csrf='))?.split('=')[1] ?? ''
}

export function localTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(new Date(value)).replaceAll('/', '-')
}
