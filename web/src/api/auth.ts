import { api } from './client'
import type { MeResponse, OtpRequestResult, OtpVerifyResult } from '@/types'

export function requestOtp(email: string, invite?: string): Promise<OtpRequestResult> {
  const body: Record<string, string> = { email }
  if (invite) body.invite = invite
  return api.post<OtpRequestResult>('/auth/otp/request', body)
}

export function verifyOtp(payload: {
  email: string
  code: string
  invite?: string
}): Promise<OtpVerifyResult> {
  const body: Record<string, string> = { email: payload.email, code: payload.code }
  if (payload.invite) body.invite = payload.invite
  return api.post<OtpVerifyResult>('/auth/otp/verify', body)
}

export function logoutRequest(): Promise<{ ok?: boolean }> {
  return api.post<{ ok?: boolean }>('/auth/logout')
}

export function fetchMe(): Promise<MeResponse> {
  return api.get<MeResponse>('/me')
}
