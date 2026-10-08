import type { MetadataForm } from './moldMetadataForm'

export default function MoldMetadataFields({ value, onChange }: { value: MetadataForm; onChange: (next: MetadataForm) => void }) {
  function change(field: keyof MetadataForm, next: string) { onChange({ ...value, [field]: next }) }
  return <>
    <label>模具厂家<input value={value.manufacturer} maxLength={100} placeholder="例如：弘晟" onChange={(event) => change('manufacturer', event.target.value)} /></label>
    <label>排模双数<input type="number" min={1} max={99} step={1} value={value.pairs_per_mold} placeholder="1 表示一模一双" onChange={(event) => change('pairs_per_mold', event.target.value)} /></label>
    <label>鞋底材质<input value={value.sole_material} maxLength={30} placeholder="例如：MD" onChange={(event) => change('sole_material', event.target.value)} /></label>
    <label>初始季度<input value={value.initial_quarter} maxLength={5} pattern="[0-9]{2}[Qq][1-4]" placeholder="例如：26Q4" onChange={(event) => change('initial_quarter', event.target.value)} /></label>
    <label>开制日期<input type="text" inputMode="numeric" maxLength={10} pattern="[0-9]{4}[-.][0-9]{1,2}[-.][0-9]{1,2}" placeholder="例如：2026.3.16" value={value.opened_on} onChange={(event) => change('opened_on', event.target.value)} /></label>
  </>
}
