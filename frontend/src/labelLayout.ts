export interface LabelSettings {
  width: number; height: number; paper: 'label' | 'a4'; gap: number
  marginX: number; marginY: number; padding: number; qrSize: number; textGap: number; fontSize: number
  border: boolean
}
export interface EditableLabel { code: string; qrContent: string; rows: string[]; qrSvg: string }
export interface LabelPosition { index: number; x: number; y: number }
export interface LabelPage { positions: LabelPosition[] }
export const defaultLabelSettings: LabelSettings = { width: 100, height: 50, paper: 'label', gap: 2, marginX: 4, marginY: 4, padding: 2, qrSize: 40, textGap: 2, fontSize: 10.5, border: false }

export const compactLabelSettings = { width: 60, height: 25, padding: 1, qrSize: 20, textGap: 1, fontSize: 6.5 }

// Self-contained so the same layout engine can run inside the offline HTML editor.
// Coordinates and SVG viewBox units are millimetres, never screen pixels.
export function createLabelLayout() {
  const fontFamily = "SimSun, 'Songti SC', 'Noto Serif CJK SC', serif"
  function escape(value: string) { return value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]!) }
  function number(value: number) { return Number(value.toFixed(4)) }
  function geometry(settings: LabelSettings) {
    const { width, height, paper, gap, marginX, marginY, padding, qrSize, textGap, fontSize } = settings
    if (![width, height, gap, marginX, marginY, padding, qrSize, textGap, fontSize].every(Number.isFinite)) throw new Error('尺寸必须是有效数字')
    if (paper !== 'label' && paper !== 'a4') throw new Error('请选择标签纸或 A4 纸')
    if (width < 35 || width > 150 || height < 25 || height > 100) throw new Error('标签宽需为 35～150 mm，高需为 25～100 mm')
    if (gap < 0 || gap > 15 || marginX < 0 || marginY < 0 || marginX > 50 || marginY > 50) throw new Error('间距需为 0～15 mm，页面边距需为 0～50 mm')
    if (padding < 1 || padding > 10 || textGap < 1 || textGap > 10 || fontSize < 5.5 || fontSize > 24) throw new Error('内边距和图文间距需为 1～10 mm，字号需为 5.5～24 pt')
    const innerHeight = height - 2 * padding
    const textX = padding + qrSize + 0.25 + textGap
    const textWidth = width - padding - textX
    if (qrSize < 12 || qrSize > innerHeight || textWidth < 12) throw new Error('二维码或文字超出标签，请减小二维码/边距，或增大标签尺寸')
    const pageWidth = paper === 'label' ? width : 210
    const pageHeight = paper === 'label' ? height : 297
    const left = paper === 'label' ? 0 : marginX
    const top = paper === 'label' ? 0 : marginY
    const columns = Math.floor((pageWidth - 2 * left + gap + 1e-8) / (width + gap))
    const rows = Math.floor((pageHeight - 2 * top + gap + 1e-8) / (height + gap))
    if (columns < 1 || rows < 1) throw new Error('标签放不进所选纸张，请减小标签或页面边距')
    return { pageWidth, pageHeight, left, top, columns, rows, perPage: columns * rows, innerHeight, textX, textWidth }
  }
  function paginate(count: number, settings: LabelSettings) {
    const g = geometry(settings)
    const pages: LabelPage[] = []
    for (let index = 0; index < count; index++) {
      const pageIndex = Math.floor(index / g.perPage), slot = index % g.perPage
      if (!pages[pageIndex]) pages.push({ positions: [] })
      pages[pageIndex].positions.push({ index, x: number(g.left + (slot % g.columns) * (settings.width + settings.gap)), y: number(g.top + Math.floor(slot / g.columns) * (settings.height + settings.gap)) })
    }
    return { ...g, pages }
  }
  function measure(value: string, size: number) {
    if (typeof document !== 'undefined' && typeof document.createElement === 'function') {
      const context = document.createElement('canvas').getContext('2d')
      if (context) { context.font = `${size * 96 / 72}px ${fontFamily}`; return context.measureText(value).width * 25.4 / 96 }
    }
    return [...value].reduce((sum, char) => sum + (char.charCodeAt(0) > 127 ? 1 : 0.6), 0) * size * 25.4 / 72
  }
  function fontFor(label: EditableLabel, settings: LabelSettings) {
    const g = geometry(settings)
    const longest = Math.max(...label.rows.map((value) => measure(value, settings.fontSize)))
    const size = Math.min(settings.fontSize, g.innerHeight / label.rows.length / 1.2 * 72 / 25.4, settings.fontSize * g.textWidth / Math.max(longest, 0.001) * 0.98)
    if (size < 5.5) throw new Error(`${label.code} 的文字小于 5.5 pt，请增大标签、减小二维码或缩短资料`)
    return number(size)
  }
  function labelBody(label: EditableLabel, settings: LabelSettings) {
    const g = geometry(settings), font = fontFor(label, settings)
    const qrY = (settings.height - settings.qrSize) / 2
    const svg = label.qrSvg.replace(/<svg\b[^>]*>/, '').replace(/<\/svg>\s*$/, '')
    const fields = label.rows.map((value, index) => `<text data-field="${index + 1}" x="${number(g.textX)}" y="${number(settings.padding + (index + 0.5) * g.innerHeight / label.rows.length)}" dominant-baseline="central" font-size="${number(font * 25.4 / 72)}" font-family="${escape(fontFamily)}">${escape(value)}</text>`).join('')
    // Keep the entire stroke outside the content area, including at minimum padding.
    const border = settings.border ? `<rect data-role="border" x="0.5" y="0.5" width="${number(settings.width - 1)}" height="${number(settings.height - 1)}" fill="none" stroke="black" stroke-width="0.2"/>` : ''
    return `<g data-code="${escape(label.code)}"><title>${escape(label.code)}</title><rect width="${settings.width}" height="${settings.height}" fill="white"/><svg data-role="qr" x="${settings.padding}" y="${number(qrY)}" width="${settings.qrSize}" height="${settings.qrSize}" viewBox="0 0 360 360" shape-rendering="crispEdges">${svg}</svg><path data-role="divider" d="M ${number(settings.padding + settings.qrSize + 0.125)} ${settings.padding} v ${number(g.innerHeight)}" stroke="#214c9b" stroke-width="0.25"/>${fields}${border}</g>`
  }
  function labelSvg(label: EditableLabel, settings: LabelSettings) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${settings.width}mm" height="${settings.height}mm" viewBox="0 0 ${settings.width} ${settings.height}">${labelBody(label, settings)}</svg>`
  }
  function pageSvg(labels: EditableLabel[], settings: LabelSettings, pageIndex: number, guides = false) {
    const plan = paginate(labels.length, settings), page = plan.pages[pageIndex]
    if (!page) throw new Error('没有可导出的标签页')
    const extra = guides ? 10 : 0
    let rulers = ''
    if (guides) {
      for (let x = 0; x <= plan.pageWidth; x += 10) rulers += `<path d="M ${x + extra} 6 v 4" stroke="#718779" stroke-width="0.2"/><text x="${x + extra}" y="4.5" text-anchor="middle" font-size="2.4" fill="#52665a">${x}</text>`
      for (let y = 0; y <= plan.pageHeight; y += 10) rulers += `<path d="M 6 ${y + extra} h 4" stroke="#718779" stroke-width="0.2"/><text x="4.5" y="${y + extra}" text-anchor="middle" dominant-baseline="central" font-size="2.4" fill="#52665a">${y}</text>`
    }
    const cards = page.positions.map((position) => `<g id="label-${position.index + 1}" transform="translate(${position.x} ${position.y})">${labelBody(labels[position.index], settings)}${guides ? `<rect width="${settings.width}" height="${settings.height}" fill="none" stroke="#d77c29" stroke-width="0.2" stroke-dasharray="1 1"/><rect x="${settings.padding}" y="${number((settings.height - settings.qrSize) / 2)}" width="${settings.qrSize}" height="${settings.qrSize}" fill="none" stroke="#538dbb" stroke-width="0.15" stroke-dasharray="1 1"/>` : ''}</g>`).join('')
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${plan.pageWidth + 2 * extra}mm" height="${plan.pageHeight + 2 * extra}mm" viewBox="0 0 ${plan.pageWidth + 2 * extra} ${plan.pageHeight + 2 * extra}"><title>标签排版 ${plan.pageWidth} × ${plan.pageHeight} mm · 第 ${pageIndex + 1} 页</title>${rulers}<g transform="translate(${extra} ${extra})"><rect width="${plan.pageWidth}" height="${plan.pageHeight}" fill="white"/>${cards}${guides ? `<rect width="${plan.pageWidth}" height="${plan.pageHeight}" fill="none" stroke="#718779" stroke-width="0.2"/>` : ''}</g></svg>`
  }
  return { geometry, paginate, fontFor, labelSvg, pageSvg }
}
