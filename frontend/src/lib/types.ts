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
