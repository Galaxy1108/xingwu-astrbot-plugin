import { api } from './client'
import type {
  MeResponse,
  OAuthIdentity,
  OAuthProvider,
  OAuthStartResult,
  OtpRequestResult,
  OtpVerifyResult,
  PasswordRegisterPayload,
  PasswordSessionResult,
  User,
} from '@/types'

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

/** 更新显示名/用户名，返回更新后的用户。 */
export function updateProfile(payload: {
  display_name?: string
  username?: string
}): Promise<{ user: User }> {
  return api.patch<{ user: User }>('/me/profile', payload)
}

export function passwordLogin(
  identifier: string,
  password: string,
): Promise<PasswordSessionResult> {
  return api.post<PasswordSessionResult>('/auth/password/login', { identifier, password })
}

export function passwordRegister(payload: PasswordRegisterPayload): Promise<PasswordSessionResult> {
  return api.post<PasswordSessionResult>('/auth/password/register', payload)
}

export function requestPasswordReset(
  email: string,
): Promise<{ sent: boolean; dev_code?: string }> {
  return api.post<{ sent: boolean; dev_code?: string }>('/auth/password/reset/request', { email })
}

export function resetPassword(payload: {
  email: string
  code: string
  password: string
}): Promise<{ ok?: boolean }> {
  return api.post<{ ok?: boolean }>('/auth/password/reset', payload)
}

export function requestEmailBind(
  email: string,
): Promise<{ sent: boolean; dev_code?: string }> {
  return api.post<{ sent: boolean; dev_code?: string }>('/auth/email/bind/request', { email })
}

export function bindEmail(payload: { email: string; code: string }): Promise<{ user: User }> {
  return api.post<{ user: User }>('/auth/email/bind', payload)
}

export function setMyPassword(payload: {
  new_password: string
  current_password?: string
}): Promise<{ user: User }> {
  return api.post<{ user: User }>('/me/password', payload)
}

export function getOAuthProviders(): Promise<{ providers: OAuthProvider[] }> {
  return api.get<{ providers: OAuthProvider[] }>('/auth/oauth/providers')
}

export function startOAuth(
  provider: string,
  mode: 'login' | 'register' | 'bind',
  options: { redirect?: string; invite?: string } = {},
): Promise<OAuthStartResult> {
  return api.get<OAuthStartResult>(`/auth/oauth/${encodeURIComponent(provider)}/start`, {
    mode,
    redirect: options.redirect,
    invite: options.invite,
  })
}

export function getMyOAuth(): Promise<{ items: OAuthIdentity[] }> {
  return api.get<{ items: OAuthIdentity[] }>('/me/oauth')
}

export function unbindOAuth(provider: string): Promise<{ unbound?: boolean }> {
  return api.post<{ unbound?: boolean }>(
    `/me/oauth/${encodeURIComponent(provider)}/unbind`,
  )
}
