/** Made-up report data for tests, shaped like the backend's responses. */
import type { ExtractedRow, MetricDefinition, ReportReview } from '../lib/types'

export const DICTIONARY: MetricDefinition[] = [
  {
    id: 'metric-hb',
    canonical_name: 'Hemoglobin',
    category: 'Complete blood count',
    canonical_unit: 'g/dL',
    aliases: ['HGB', 'Hb'],
    description: null,
  },
  {
    id: 'metric-ferritin',
    canonical_name: 'Ferritin',
    category: 'Iron studies',
    canonical_unit: 'ng/mL',
    aliases: [],
    description: null,
  },
  {
    id: 'metric-b12',
    canonical_name: 'Vitamin B12',
    category: 'Vitamins',
    canonical_unit: 'pg/mL',
    aliases: ['Cobalamin'],
    description: null,
  },
]

const base: ExtractedRow = {
  raw_name: '',
  panel: null,
  technology: null,
  method: null,
  sample_type: 'Serum',
  value_text: '',
  value_numeric: null,
  unit: null,
  canonical_metric_id: null,
  canonical_name: null,
  value_canonical: null,
  unit_canonical: null,
  reference_text: null,
  reference_low: null,
  reference_high: null,
  reference_label: null,
  flag: 'unknown',
  warnings: [],
}

export const UNKNOWN_TEST_WARNING =
  'Not in the metric dictionary yet: choose the matching test or keep it as is'

export const ROWS: ExtractedRow[] = [
  {
    ...base,
    raw_name: 'HAEMOGLOBIN',
    panel: 'COMPLETE BLOOD COUNT',
    sample_type: 'Whole blood',
    value_text: '13.5',
    value_numeric: '13.5',
    unit: 'g/dL',
    canonical_metric_id: 'metric-hb',
    canonical_name: 'Hemoglobin',
    reference_text: 'Female: 12.0 - 15.0',
    reference_low: '12.0',
    reference_high: '15.0',
    reference_label: 'Female',
    flag: 'normal',
  },
  {
    ...base,
    raw_name: 'FERRITIN',
    value_text: '8.2',
    value_numeric: '8.2',
    unit: 'ng/mL',
    canonical_metric_id: 'metric-ferritin',
    canonical_name: 'Ferritin',
    reference_text: 'Female: 13 - 150',
    reference_low: '13',
    reference_high: '150',
    reference_label: 'Female',
    flag: 'low',
  },
  {
    ...base,
    raw_name: 'COBALAMIN',
    value_text: '410',
    value_numeric: '410',
    unit: 'pg/mL',
    reference_text: '197 - 771',
    reference_low: '197',
    reference_high: '771',
    warnings: [UNKNOWN_TEST_WARNING],
  },
  {
    ...base,
    raw_name: 'URINE GLUCOSE',
    sample_type: 'Urine',
    value_text: 'Negative',
  },
]

export function sampleReview(): Omit<ReportReview, 'report'> {
  return {
    printed_age_years: 58,
    printed_sex: 'female',
    sample_types: ['Serum', 'Urine', 'Whole blood'],
    warnings: [],
    rows: ROWS,
  }
}
