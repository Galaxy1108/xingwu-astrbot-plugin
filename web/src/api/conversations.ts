import { api } from './client'
import type {
  ConversationShare,
  ConversationSummary,
  PageResult,
  PublicConversation,
} from '@/types'

export function listConversations(
  botId: string,
  page = 1,
  pageSize = 20,
): Promise<PageResult<ConversationSummary>> {
  return api.get<PageResult<ConversationSummary>>(
    `/bots/${encodeURIComponent(botId)}/conversations`,
    { page, page_size: pageSize },
  )
}

export function getConversation(
  botId: string,
  conversationId: string,
): Promise<{ conversation: ConversationSummary }> {
  return api.get<{ conversation: ConversationSummary }>(
    `/bots/${encodeURIComponent(botId)}/conversations/${encodeURIComponent(conversationId)}`,
  )
}

export function shareConversation(
  botId: string,
  conversationId: string,
  expiresHours?: number,
): Promise<{ share: ConversationShare }> {
  return api.post<{ share: ConversationShare }>(
    `/bots/${encodeURIComponent(botId)}/conversations/${encodeURIComponent(conversationId)}/share`,
    expiresHours ? { expires_hours: expiresHours } : {},
  )
}

export function revokeConversationShare(
  botId: string,
  conversationId: string,
): Promise<{ revoked?: boolean }> {
  return api.delete<{ revoked?: boolean }>(
    `/bots/${encodeURIComponent(botId)}/conversations/${encodeURIComponent(conversationId)}/share`,
  )
}

export function getPublicConversation(token: string): Promise<PublicConversation> {
  return api.get<PublicConversation>(
    `/public/conversations/${encodeURIComponent(token)}`,
  )
}
