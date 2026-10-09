const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, '../src/moldLabel.ts'), 'utf8')
const moduleUnderTest = { exports: {} }
new Function('module', 'exports', ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(moduleUnderTest, moduleUnderTest.exports)
const { moldLabelRows, moldProfileRows, moldName, setName, standardSizes } = moduleUnderTest.exports

test('label displays the seven agreed fields and date format', () => {
  assert.deepEqual(moldLabelRows({ kind: 'MOLD', code: 'QD-264301-A-42', mold_number: 'QD-264301', manufacturer: '弘晟', mold_category: 'A模', size_label: '42#', pairs_per_mold: 1, sole_material: 'MD', initial_quarter: '26Q4', opened_on: '2026-03-16' }).map(([key, value]) => `${key}：${value}`), [
    '模具厂家：弘晟', '模具编号：QD-264301', '模具类别：A模', '模具码数：42#', '鞋底材质：MD', '初始季度：26Q4', '开制日期：2026.3.16',
  ])
})

test('old labels preserve code and size without inventing missing metadata', () => {
  const rows = moldLabelRows({ kind: 'MOLD', code: 'OLD-1', size_label: '42' })
  assert.equal(rows[1][1], 'OLD-1')
  assert.equal(rows[3][1], '42#')
  assert.equal(rows.filter(([, value]) => value === '—').length, 5)
  assert.equal(moldProfileRows({ code: 'X', pairs_per_mold: 12 })[4][1], '一模十二双')
})

test('identities distinguish A/B and half sizes while printed number stays the style number', () => {
  assert.equal(moldName({ code: 'QD-264301-A-40.5', mold_number: 'QD-264301', mold_category: 'A模', size_label: '40.5' }), 'QD-264301 · A模 · 40.5#')
  assert.equal(moldName({ code: 'QD-264301-B-42', model_code: 'QD-264301', mold_category: 'B模', size_label: '42' }), 'QD-264301 · B模 · 42#')
  assert.equal(setName({ model_code: 'OLD' }), 'OLD · 历史未分类')
  assert.equal(moldName({ code: 'CHILD-A-32', model_code: 'CHILD', mold_category: 'A模', shoe_type: '女童', size_label: '32' }), 'CHILD · A模 · 女童 · 32#')
  assert.deepEqual(standardSizes, ['39', '40', '40.5', '41', '42', '42.5', '43', '44', '44.5', '45'])
})

test('size plans preserve half sizes and reject duplicates or unsupported fractions', () => {
  const sizesModule = { exports: {} }
  new Function('module', 'exports', ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/shoeSizes.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(sizesModule, sizesModule.exports)
  const { parseSizeList, sizePresets, littleKidsSizes } = sizesModule.exports
  assert.deepEqual(parseSizeList('36, 35.50＃、35'), ['35', '35.5', '36'])
  assert.throws(() => parseSizeList('35.5,35.50'), /不重复/)
  assert.throws(() => parseSizeList('35.25'), /半码/)
  assert.deepEqual(sizePresets.男童, sizePresets.女童)
  assert.equal(littleKidsSizes.length, 10)
})
