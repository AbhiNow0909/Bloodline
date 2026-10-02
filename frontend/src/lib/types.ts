/** Shapes returned by the Bloodline API (see backend/app/schemas). Ids are UUID strings;
 * timestamps are ISO 8601; dates of birth are "YYYY-MM-DD". */

export type Sex = 'male' | 'female'

export interface User {
  id: string
  email: string
  display_name: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface Family {
  id: string
  name: string
  created_at: string
  patient_count: number
}

/** A family member ("patient" in the API). */
export interface Member {
  id: string
  family_id: string
  display_name: string
  sex: Sex
  date_of_birth: string | null
  created_at: string
}

export interface MemberInput {
  display_name: string
  sex: Sex
  date_of_birth: string | null
}

// --- reports -------------------------------------------------------------------------------
// Decimals arrive as exact strings (e.g. "13.50"), never floats.

export type ReportStatus = 'processing' | 'pending_review' | 'confirmed' | 'failed'
export type MetricFlag = 'low' | 'normal' | 'high' | 'unknown'

export interface Report {
  id: string
  patient_id: string
  status: ReportStatus
  lab_name: string | null
  collected_at: string | null
  failure_reason: string | null
  created_at: string
}

export interface ReportSummary extends Report {
  metric_count: number
  flagged_count: number
}

/** One extracted row, waiting for review. */
export interface ExtractedRow {
  raw_name: string
  panel: string | null
  technology: string | null
  method: string | null
  sample_type: string | null
  value_text: string
  value_numeric: string | null
  unit: string | null
  canonical_metric_id: string | null
  canonical_name: string | null
  value_canonical: string | null
  unit_canonical: string | null
  reference_text: string | null
  reference_low: string | null
  reference_high: string | null
  reference_label: string | null
  flag: MetricFlag
  warnings: string[]
}

export interface ReportReview {
  report: Report
  printed_age_years: number | null
  printed_sex: Sex | null
  sample_types: string[]
  warnings: string[]
  rows: ExtractedRow[]
}

/** A reviewed row sent to POST /reports/{id}/confirm. The server derives every number. */
export interface ConfirmedRow {
  raw_name: string
  canonical_metric_id: string | null
  value_text: string
  unit: string | null
  reference_low: string | null
  reference_high: string | null
  reference_text: string | null
  sample_type: string | null
  method: string | null
}

export interface ConfirmReportInput {
  collected_at?: string
  metrics: ConfirmedRow[]
}

/** A saved value. */
export interface Reading {
  patient_id: string
  report_id: string
  collected_at: string
  canonical_metric_id: string | null
  raw_name: string
  value_text: string | null
  value_numeric: string | null
  unit: string | null
  value_canonical: string | null
  unit_canonical: string | null
  reference_low: string | null
  reference_high: string | null
  reference_text: string | null
  flag: MetricFlag
}

/** A test the app knows (the metric dictionary). */
export interface MetricDefinition {
  id: string
  canonical_name: string
  category: string
  canonical_unit: string
  aliases: string[]
  description: string | null
}

// --- history (confirmed values) -------------------------------------------------------------

/** A test the app knows, as attached to history. */
export interface MetricInfo {
  id: string
  canonical_name: string
  category: string
  canonical_unit: string
  description: string | null
}

/** A test the member has results for. Tests not in the dictionary have `metric` null and no
 * history chart. */
export interface CatalogEntry {
  metric: MetricInfo | null
  name: string
  reading_count: number
  first_collected_at: string
  latest: Reading
}

/** A reading on a chart, with its range also in the test's canonical unit. */
export interface HistoryPoint extends Reading {
  reference_low_canonical: string | null
  reference_high_canonical: string | null
}

export interface MetricHistory {
  metric: MetricInfo
  points: HistoryPoint[] // oldest first
}

export interface FlaggedReading extends Reading {
  name: string
  category: string | null
}

export interface MemberOverview {
  patient: Member
  latest_report_at: string | null
  tracked_metric_count: number
  out_of_range: FlaggedReading[]
}

export interface FamilyOverview {
  family_id: string
  name: string
  members: MemberOverview[]
}

// --- chat ------------------------------------------------------------------------------------

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/** A report an answer drew on. */
export interface ChatSource {
  report_id: string
  collected_at: string
  lab_name: string | null
  member_id: string
  member_name: string
}

export interface ChatReply {
  reply: string
  sources: ChatSource[]
  disclaimer: string
}
