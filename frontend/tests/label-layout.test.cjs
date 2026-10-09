const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
function load(name, dependencies = {}) {
  const module = { exports: {} }
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', name + '.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  new Function('require', 'module', 'exports', code)((name) => dependencies[name] ?? require(name), module, module.exports)
  return module.exports
}
const layout = load('labelLayout')
const { labelEditorHtml } = load('labelExport', { './labelLayout': layout })
const settings = layout.defaultLabelSettings
const engine = layout.createLabelLayout()
const label = { code: 'QD-264301-A-42', qrContent: 'MOLD:QD-264301-A-42', rows: ['模具厂家：弘晟', '模具编号：QD-264301', '模具类别：A模', '模具码数：42#', '鞋底材质：MD', '初始季度：26Q4', '开制日期：2026.3.16'], qrSvg: '<svg width="360" height="360"><rect x="40" y="40" width="20" height="20"/></svg>' }

test('label paper uses its actual physical page size and one label per page', () => {
  const plan = engine.paginate(3, settings)
  assert.equal(plan.pageWidth, 100); assert.equal(plan.pageHeight, 50)
  assert.equal(plan.pages.length, 3)
  assert.deepEqual(plan.pages[2].positions, [{ index: 2, x: 0, y: 0 }])
  const svg = engine.pageSvg([label], settings, 0)
  assert.match(svg, /width="100mm" height="50mm" viewBox="0 0 100 50"/)
  assert.equal((svg.match(/<text /g) || []).length, 7)
  assert.equal(svg.includes('stroke-dasharray'), false)
})
test('A4 positions account for both margins, gaps, bounds and page breaks', () => {
  const plan = engine.paginate(11, { ...settings, paper: 'a4' })
  assert.deepEqual([plan.pageWidth, plan.pageHeight, plan.columns, plan.rows], [210, 297, 2, 5])
  assert.equal(plan.pages.length, 2)
  assert.deepEqual(plan.pages[0].positions[9], { index: 9, x: 106, y: 212 })
  assert.deepEqual(plan.pages[1].positions, [{ index: 10, x: 4, y: 4 }])
  for (const page of plan.pages) for (const p of page.positions) {
    assert.ok(p.x >= 4 && p.x + settings.width <= 206)
    assert.ok(p.y >= 4 && p.y + settings.height <= 293)
  }
  assert.throws(() => engine.paginate(1, { ...settings, paper: 'a4', marginX: 50, width: 150 }), /放不进/)
})
test('preview rulers never change clean export size or add guides to printing', () => {
  const preview = engine.pageSvg([label], settings, 0, true)
  const clean = engine.pageSvg([label], settings, 0)
  assert.match(preview, /width="120mm" height="70mm"/)
  assert.match(preview, /translate\(10 10\)/)
  assert.match(preview, /stroke-dasharray/)
  assert.match(clean, /width="100mm" height="50mm"/)
  assert.ok(!clean.includes('stroke-dasharray'))
  assert.match(clean, /width="40" height="40" viewBox="0 0 360 360"/)
})
test('invalid geometry and unreadably long text are rejected instead of clipping', () => {
  for (const changes of [{ width: NaN }, { height: 0 }, { qrSize: 48 }, { qrSize: 90 }, { gap: -1 }, { fontSize: 5 }, { padding: 0 }]) {
    assert.throws(() => engine.geometry({ ...settings, ...changes }))
  }
  assert.equal(engine.fontFor(label, settings), 10.5)
  assert.throws(() => engine.fontFor({ ...label, rows: ['厂家：' + '厂'.repeat(100), ...label.rows.slice(1)] }, settings), /小于 5.5 pt/)
})
test('label text cannot introduce SVG markup or break out of the offline data script', () => {
  const dangerous = { ...label, rows: ['厂家：</script><img src=x onerror=alert(1)>', ...label.rows.slice(1)] }
  const svg = engine.labelSvg({ ...dangerous, rows: ['厂家：<b>&"', ...label.rows.slice(1)] }, settings)
  assert.ok(svg.includes('&lt;b&gt;&amp;&quot;'))
  assert.ok(!svg.includes('<b>'))
  const html = labelEditorHtml([dangerous], settings)
  const data = html.match(/<script id="label-data" type="application\/json">([\s\S]*?)<\/script>/)[1]
  assert.equal(JSON.parse(data).labels[0].rows[0], dangerous.rows[0])
  assert.ok(!data.includes('<'))
  const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1]
  assert.doesNotThrow(() => new Function(script))
  assert.ok(!html.includes('<script src='))
})
test('offline editor embeds the same engine without module or server dependencies', () => {
  const restoredEngine = new Function('return (' + layout.createLabelLayout.toString() + ')()')()
  assert.equal(restoredEngine.pageSvg([label], settings, 0), engine.pageSvg([label], settings, 0))
  const html = labelEditorHtml([label], settings)
  assert.match(html, /保存编辑文件/)
  assert.match(html, /文字第 /)
  assert.match(html, /readOnly/)
  assert.match(html, /@page\{size:/)
})
