export type ShoeType = '男鞋' | '女鞋' | '女童' | '男童'
export const shoeTypes: ShoeType[] = ['男鞋', '女鞋', '女童', '男童']
export const menSizes = ['39', '40', '40.5', '41', '42', '42.5', '43', '44', '44.5', '45']
export const womenSizes = ['35.5', '36', '36.5', '37.5', '38', '38.5', '39', '40', '40.5', '41']
export const bigKidsSizes = ['32', '33', '33.5', '34', '35', '35.5', '36', '36.5', '37.5', '38']
export const littleKidsSizes = ['25', '26', '27', '27.5', '28', '28.5', '29.5', '30', '31', '31.5']
export const sizePresets: Record<ShoeType, string[]> = { 男鞋: menSizes, 女鞋: womenSizes, 女童: bigKidsSizes, 男童: bigKidsSizes }

export function parseSizeList(text: string): string[] {
  const sizes = text.trim().split(/[、,，;；/\s]+/).filter(Boolean).map((value) => {
    const size = value.replace(/[#＃]+$/, '')
    if (!/^[0-9]{1,3}(?:\.[05]0*)?$/.test(size) || Number(size) <= 0 || Number(size) >= 1000) throw new Error('码数须为正整数或半码，例如 35、35.5')
    return String(Number(size))
  })
  if (!sizes.length || sizes.length > 100 || new Set(sizes).size !== sizes.length) throw new Error('整套码数须为 1～100 个不重复码数')
  return sizes.sort((a, b) => Number(a) - Number(b))
}
