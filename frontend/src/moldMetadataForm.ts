import type { MoldMetadata } from './moldLabel'

export interface MetadataForm {
  manufacturer: string
  pairs_per_mold: string
  sole_material: string
  initial_quarter: string
  opened_on: string
}

export function metadataForm(mold: MoldMetadata = {}): MetadataForm {
  return {
    manufacturer: mold.manufacturer ?? '',
    pairs_per_mold: mold.pairs_per_mold == null ? '' : String(mold.pairs_per_mold),
    sole_material: mold.sole_material ?? '', initial_quarter: mold.initial_quarter ?? '', opened_on: mold.opened_on ?? '',
  }
}

export function metadataPayload(form: MetadataForm): MoldMetadata {
  return {
    manufacturer: form.manufacturer.trim() || null,
    pairs_per_mold: form.pairs_per_mold ? Number(form.pairs_per_mold) : null,
    sole_material: form.sole_material.trim() || null, initial_quarter: form.initial_quarter.trim().toUpperCase() || null, opened_on: form.opened_on || null,
  }
}
