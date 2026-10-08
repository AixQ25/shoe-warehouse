export interface MoldMetadata {
  manufacturer?: string | null
  mold_category?: string | null
  pairs_per_mold?: number | null
  sole_material?: string | null
  initial_quarter?: string | null
  opened_on?: string | null
}

export interface LabelData extends MoldMetadata {
  shoe_type?: string | null
  kind: 'MOLD' | 'LOCATION'
  code: string
  mold_number?: string
  qr_content: string
  name: string
  size_label?: string
}

function chineseNumber(value: number): string {
  const digits = '零一二三四五六七八九'
  if (value < 10) return digits[value]
  const tens = Math.floor(value / 10), units = value % 10
  return `${tens === 1 ? '' : digits[tens]}十${units ? digits[units] : ''}`
}

export function moldLabelRows(label: LabelData): [string, string][] {
  const size = label.size_label?.trim().replace(/[#＃]+$/, '').trim()
  const date = label.opened_on?.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  return [
    ['模具厂家', label.manufacturer || '—'],
    ['模具编号', label.mold_number || label.code],
    ['模具类别', label.mold_category || '—'],
    ['模具码数', size ? `${size}#` : '—'],
    ['排模双数', label.pairs_per_mold ? `一模${chineseNumber(label.pairs_per_mold)}双` : '—'],
    ['鞋底材质', label.sole_material || '—'],
    ['初始季度', label.initial_quarter || '—'],
    ['开制日期', date ? `${date[1]}.${Number(date[2])}.${Number(date[3])}` : '—'],
  ]
}

export const standardSizes = ['39', '40', '40.5', '41', '42', '42.5', '43', '44', '44.5', '45']

export function setName(item: { model_code?: string; mold_number?: string; mold_category?: string | null; shoe_type?: string | null; set_code?: string }): string {
  return `${item.mold_number || item.model_code || item.set_code || '未知款号'} · ${item.mold_category || '历史未分类'}${item.shoe_type ? ` · ${item.shoe_type}` : ''}`
}

export function moldName(item: { code: string; model_code?: string; mold_number?: string; mold_category?: string | null; shoe_type?: string | null; size_label: string }): string {
  return `${setName(item)} · ${item.size_label.replace(/[#＃]+$/, '')}#`
}
