import {
  inject,
  provide,
  reactive,
  ref,
  watch,
  type ComputedRef,
  type InjectionKey,
} from 'vue'
import { useUiStore } from '@/stores/ui'
import { isApiError, toApiError } from '@/api/client'
import { downloadJson } from '@/utils/download'
import { errorMessage } from '@/utils/errors'
import {
  deleteAdminBotMemory,
  exportAdminBotMemories,
  deleteAdminBotNote,
  importAdminBotMemories,
  listAdminBotConversations,
  listAdminBotNotes,
  listAdminBotMemories,
  patchAdminBotMemory,
  readAdminBotNote,
} from '@/api/admin'
import type {
  AdminConversation,
  MemoryImportReport,
  MemoryItem,
  NoteReadPage,
  NoteSummary,
  MemoryKind,
  MemoryPatch,
} from '@/types'

export interface AdminContentOptions {
  /** 抽屉是否可见（对应 modelValue）。 */
  visible: ComputedRef<boolean>
  /** 当前查看的 Bot id（对应 bot.id）。 */
  botId: ComputedRef<string>
  /** 窄屏标记，影响会话的默认选中与列表/消息切换。 */
  isNarrow: ComputedRef<boolean>
}

/**
 * AdminContentDrawer 的共享状态与请求逻辑。
 *
 * 父组件（AdminContentDrawer）创建一次并通过 provide 下发给各子组件，
 * 子组件通过 useAdminContentContext() 读取。逻辑与拆分前保持一致：
 * 加密确认（confirm=1）重试、访问提示、loading/error 等均集中在此。
 */
export function useAdminContent(options: AdminContentOptions) {
  const { visible, botId, isNarrow } = options
  const ui = useUiStore()

  /* ------------------------------------------------------------ tabs */
  const activeTab = ref<'conversations' | 'memories' | 'notes'>('conversations')

  /* ------------------------------------------------ encrypted confirmation */
  const contentConfirmed = ref(false)
  const confirmationOpen = ref(false)
  const confirmationMessage = ref('')
  const cancelled = ref(false)
  const encryptedNotice = ref(false)
  let pendingRetry: (() => Promise<void>) | null = null

  function isConfirmationRequired(error: unknown): boolean {
    return isApiError(error) && error.code === 'confirmation_required'
  }

  function requestContentConfirmation(message: string, retry: () => Promise<void>): void {
    confirmationMessage.value =
      message ||
      '对方已启用加密，确定要查看吗？这将解密内容并记录本次访问（用户可见）。'
    pendingRetry = retry
    confirmationOpen.value = true
  }

  async function confirmContentAccess(): Promise<void> {
    contentConfirmed.value = true
    encryptedNotice.value = true
    cancelled.value = false
    confirmationOpen.value = false
    const retry = pendingRetry
    pendingRetry = null
    if (retry) await retry()
  }

  function cancelContentAccess(): void {
    confirmationOpen.value = false
    pendingRetry = null
    cancelled.value = true
    conversations.value = []
    memories.value = []
    conversationsError.value = ''
    memoryError.value = ''
  }

  /* ------------------------------------------------------ conversations */
  const conversations = ref<AdminConversation[]>([])
  const conversationsLoading = ref(false)
  const conversationsError = ref('')
  const activeConversationId = ref('')

  async function loadConversations(confirm = contentConfirmed.value): Promise<void> {
    if (!botId.value) return
    conversationsLoading.value = true
    conversationsError.value = ''
    cancelled.value = false
    try {
      const result = await listAdminBotConversations(botId.value, confirm)
      conversations.value = result.items ?? []
      if (confirm && conversations.value.some((item) => item.encrypted)) {
        encryptedNotice.value = true
      }
      if (
        activeConversationId.value &&
        !conversations.value.some((item) => item.id === activeConversationId.value)
      ) {
        activeConversationId.value = ''
      }
      if (!activeConversationId.value && !isNarrow.value && conversations.value.length) {
        activeConversationId.value = conversations.value[0].id
      }
    } catch (error) {
      if (isConfirmationRequired(error)) {
        cancelled.value = false
        requestContentConfirmation(errorMessage(error), () => loadConversations(true))
        return
      }
      conversationsError.value = errorMessage(error, '加载对话失败')
    } finally {
      conversationsLoading.value = false
    }
  }

  function selectConversation(conversation: AdminConversation): void {
    activeConversationId.value = conversation.id
  }

  /* ----------------------------------------------------------- memories */
  const memories = ref<MemoryItem[]>([])
  const memoryTotal = ref(0)
  const memoryPage = ref(1)
  const memoryPageSize = ref(10)
  const memoryLoading = ref(false)
  const memoryError = ref('')
  const memoryLoaded = ref(false)
  const memoryFilters = reactive({ q: '', kind: '' })

  async function loadMemories(page = 1, confirm = contentConfirmed.value): Promise<void> {
    if (!botId.value) return
    memoryLoading.value = true
    memoryError.value = ''
    cancelled.value = false
    try {
      const result = await listAdminBotMemories(
        botId.value,
        {
          page,
          page_size: memoryPageSize.value,
          q: memoryFilters.q || undefined,
          kind: memoryFilters.kind || undefined,
        },
        confirm,
      )
      memories.value = result.items ?? []
      memoryTotal.value = result.total ?? 0
      memoryPage.value = result.page ?? page
      memoryPageSize.value = result.page_size ?? memoryPageSize.value
      memoryLoaded.value = true
    } catch (error) {
      if (isConfirmationRequired(error)) {
        cancelled.value = false
        requestContentConfirmation(errorMessage(error), () => loadMemories(page, true))
        return
      }
      memoryError.value = errorMessage(error, '加载记忆失败')
    } finally {
      memoryLoading.value = false
    }
  }

  function applyMemoryFilters(): void {
    void loadMemories(1)
  }

  function resetMemoryFilters(): void {
    memoryFilters.q = ''
    memoryFilters.kind = ''
    void loadMemories(1)
  }

  /* ------------------------------------------------------------ notes */
  const notes = ref<NoteSummary[]>([])
  const notesTotal = ref(0)
  const notesPage = ref(1)
  const notesPageSize = ref(10)
  const notesLoading = ref(false)
  const notesError = ref('')
  const notesLoaded = ref(false)
  const noteFilters = reactive({ q: '', tag: '' })
  const noteViewerOpen = ref(false)
  const selectedNote = ref<NoteSummary | null>(null)
  const noteRead = ref<NoteReadPage | null>(null)
  const noteReadContent = ref('')
  const noteReadError = ref('')
  const noteReadMore = ref(false)
  const noteDeleteOpen = ref(false)
  const noteDeleteTarget = ref<NoteSummary | null>(null)
  const noteDeleting = ref(false)

  async function loadNotes(page = 1, confirm = contentConfirmed.value): Promise<void> {
    if (!botId.value) return
    notesLoading.value = true
    notesError.value = ''
    cancelled.value = false
    try {
      const result = await listAdminBotNotes(
        botId.value,
        {
          page,
          page_size: notesPageSize.value,
          q: noteFilters.q || undefined,
          tag: noteFilters.tag || undefined,
        },
        confirm,
      )
      notes.value = result.items ?? []
      notesTotal.value = result.total ?? 0
      notesPage.value = result.page ?? page
      notesPageSize.value = result.page_size ?? notesPageSize.value
      notesLoaded.value = true
    } catch (error) {
      if (isConfirmationRequired(error)) {
        cancelled.value = false
        requestContentConfirmation(errorMessage(error), () => loadNotes(page, true))
        return
      }
      notesError.value =
        toApiError(error).status === 404 || toApiError(error).status === 405
          ? '管理端笔记接口尚未就绪，请稍后刷新重试。'
          : errorMessage(error, '加载笔记失败')
    } finally {
      notesLoading.value = false
    }
  }

  function applyNoteFilters(): void {
    void loadNotes(1)
  }

  function resetNoteFilters(): void {
    noteFilters.q = ''
    noteFilters.tag = ''
    void loadNotes(1)
  }

  async function openNoteViewer(note: NoteSummary): Promise<void> {
    selectedNote.value = note
    noteRead.value = null
    noteReadContent.value = ''
    noteReadError.value = ''
    noteViewerOpen.value = true
    await loadNoteRead(note.short_id, 0, true, contentConfirmed.value)
  }

  async function loadNoteRead(
    shortId: string,
    offset: number,
    replace = false,
    confirm = contentConfirmed.value,
  ): Promise<void> {
    if (!botId.value) return
    noteReadMore.value = !replace
    noteReadError.value = ''
    try {
      const result = await readAdminBotNote(botId.value, shortId, confirm)
      noteRead.value = result
      noteReadContent.value = replace ? result.content : noteReadContent.value + result.content
    } catch (error) {
      if (isConfirmationRequired(error)) {
        requestContentConfirmation(errorMessage(error), () =>
          loadNoteRead(shortId, offset, replace, true),
        )
        return
      }
      noteReadError.value =
        toApiError(error).status === 404 || toApiError(error).status === 405
          ? '笔记正文接口尚未就绪，请稍后刷新重试。'
          : errorMessage(error, '加载笔记正文失败')
    } finally {
      noteReadMore.value = false
    }
  }

  async function loadMoreNote(): Promise<void> {
    if (!noteRead.value?.next_offset) return
    await loadNoteRead(noteRead.value.short_id, noteRead.value.next_offset)
  }

  function askDeleteNote(note: NoteSummary): void {
    noteDeleteTarget.value = note
    noteDeleteOpen.value = true
  }

  async function confirmDeleteNote(confirm = contentConfirmed.value): Promise<void> {
    if (!botId.value || !noteDeleteTarget.value) return
    noteDeleting.value = true
    try {
      await deleteAdminBotNote(botId.value, noteDeleteTarget.value.short_id, confirm)
      noteDeleteOpen.value = false
      noteViewerOpen.value = false
      selectedNote.value = null
      ui.notify('笔记已删除', 'success')
      await loadNotes(notesPage.value)
    } catch (error) {
      if (isConfirmationRequired(error)) {
        noteDeleteOpen.value = false
        requestContentConfirmation(errorMessage(error), () => confirmDeleteNote(true))
        return
      }
      noteDeleteOpen.value = false
      ui.notifyError(errorMessage(error, '删除笔记失败'))
    } finally {
      noteDeleting.value = false
    }
  }

  /* ------------------------------------------------------------- editor */
  const editorOpen = ref(false)
  const editingId = ref<number | null>(null)
  const editorError = ref('')
  const metadataError = ref('')
  const saving = ref(false)
  const editor = reactive({
    content: '',
    kind: 'fact' as MemoryKind,
    reasoning: '',
    importance: 3,
    pinned: false,
    tags: '',
    metadataText: '{}',
  })

  function openEditor(memory: MemoryItem): void {
    editingId.value = memory.id
    editor.content = memory.content
    editor.kind = memory.kind
    editor.reasoning = memory.reasoning || ''
    editor.importance = memory.importance || 3
    editor.pinned = Boolean(memory.pinned)
    editor.tags = (memory.tags || []).join(', ')
    editor.metadataText = JSON.stringify(memory.metadata ?? {}, null, 2)
    editorError.value = ''
    metadataError.value = ''
    editorOpen.value = true
  }

  async function saveEditor(): Promise<void> {
    if (!botId.value || editingId.value === null) return
    editorError.value = ''
    metadataError.value = ''

    const content = editor.content.trim()
    if (!content) {
      editorError.value = '记忆内容不能为空'
      return
    }
    if (content.length > 4000) {
      editorError.value = '记忆内容最多 4000 个字符'
      return
    }

    let metadata: Record<string, unknown> = {}
    if (editor.metadataText.trim()) {
      try {
        const parsed = JSON.parse(editor.metadataText) as unknown
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          metadataError.value = 'metadata 必须是 JSON 对象'
          return
        }
        metadata = parsed as Record<string, unknown>
      } catch {
        metadataError.value = 'metadata 不是合法的 JSON'
        return
      }
    }

    const payload: MemoryPatch = {
      content,
      kind: editor.kind,
      reasoning: editor.reasoning.trim(),
      importance: editor.importance,
      pinned: editor.pinned,
      tags: editor.tags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
      metadata,
    }

    saving.value = true
    try {
      await patchAdminBotMemory(botId.value, editingId.value, payload, contentConfirmed.value)
      editorOpen.value = false
      ui.notify('记忆已保存', 'success')
      await loadMemories(memoryPage.value)
    } catch (error) {
      if (isConfirmationRequired(error)) {
        requestContentConfirmation(errorMessage(error), async () => {
          await saveEditor()
        })
        return
      }
      editorError.value = errorMessage(error, '保存记忆失败')
    } finally {
      saving.value = false
    }
  }

  /* ------------------------------------------------------------- delete */
  const deleteOpen = ref(false)
  const deleteTarget = ref<MemoryItem | null>(null)
  const deleting = ref(false)

  function askDelete(memory: MemoryItem): void {
    deleteTarget.value = memory
    deleteOpen.value = true
  }

  async function confirmDelete(): Promise<void> {
    if (!botId.value || !deleteTarget.value) return
    deleting.value = true
    try {
      await deleteAdminBotMemory(botId.value, deleteTarget.value.id, contentConfirmed.value)
      deleteOpen.value = false
      ui.notify('记忆已删除', 'success')
      const targetPage =
        memories.value.length === 1 && memoryPage.value > 1 ? memoryPage.value - 1 : memoryPage.value
      await loadMemories(targetPage)
    } catch (error) {
      if (isConfirmationRequired(error)) {
        deleteOpen.value = false
        requestContentConfirmation(errorMessage(error), async () => {
          await confirmDelete()
        })
        return
      }
      deleteOpen.value = false
      ui.notifyError(errorMessage(error, '删除记忆失败'))
    } finally {
      deleting.value = false
    }
  }

  /* ------------------------------------------------------------- export / import */
  const exportConfirmOpen = ref(false)
  const exporting = ref(false)

  const importOpen = ref(false)
  const importFile = ref<File | File[] | null>(null)
  const importDryRun = ref(false)
  const importing = ref(false)
  const importError = ref('')
  const importReport = ref<MemoryImportReport | null>(null)
  let pendingSnapshot: Record<string, unknown> | null = null

  async function confirmExport(): Promise<void> {
    exportConfirmOpen.value = false
    await runExport(contentConfirmed.value)
  }

  async function runExport(confirm: boolean): Promise<void> {
    if (!botId.value) return
    exporting.value = true
    try {
      const result = await exportAdminBotMemories(botId.value, confirm)
      downloadJson(`memories-${botId.value}-admin.json`, result)
      ui.notify(`已导出 ${result.count} 条记忆（含笔记，已记录审计）`, 'success')
      await loadMemories(memoryPage.value)
    } catch (error) {
      if (isConfirmationRequired(error)) {
        requestContentConfirmation(errorMessage(error), async () => {
          await runExport(true)
        })
        return
      }
      ui.notifyError(errorMessage(error, '导出记忆失败'))
    } finally {
      exporting.value = false
    }
  }

  function openImport(): void {
    importFile.value = null
    importDryRun.value = false
    importError.value = ''
    importReport.value = null
    pendingSnapshot = null
    importOpen.value = true
  }

  function onImportFileChange(): void {
    pendingSnapshot = null
    importReport.value = null
    importError.value = ''
  }

  function pickedFile(): File | null {
    const value = importFile.value
    if (Array.isArray(value)) return value[0] ?? null
    return value
  }

  async function submitImport(confirm = contentConfirmed.value): Promise<void> {
    if (!botId.value) return
    importError.value = ''
    if (!pendingSnapshot) {
      const file = pickedFile()
      if (!file) {
        importError.value = '请选择 JSON 快照文件'
        return
      }
      try {
        const parsed = JSON.parse(await file.text()) as unknown
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          importError.value = '快照必须是 JSON 对象'
          return
        }
        pendingSnapshot = parsed as Record<string, unknown>
      } catch {
        importError.value = '文件不是合法的 JSON'
        return
      }
    }

    importing.value = true
    try {
      const report = await importAdminBotMemories(
        botId.value,
        pendingSnapshot,
        importDryRun.value,
        confirm,
      )
      importReport.value = report
      ui.notify(
        report.dry_run
          ? `预检完成：记忆 ${report.memories.imported} 条、笔记 ${report.notes.imported} 条（未写入）`
          : `导入完成：记忆 ${report.memories.imported} 条、笔记 ${report.notes.imported} 条`,
        'success',
      )
      if (!report.dry_run) await loadMemories(memoryPage.value)
    } catch (error) {
      if (isConfirmationRequired(error)) {
        requestContentConfirmation(errorMessage(error), async () => {
          await submitImport(true)
        })
        return
      }
      importError.value = errorMessage(error, '导入快照失败')
    } finally {
      importing.value = false
    }
  }

  /* -------------------------------------------------------------- shell */
  function resetState(): void {
    activeTab.value = 'conversations'
    contentConfirmed.value = false
    confirmationOpen.value = false
    confirmationMessage.value = ''
    cancelled.value = false
    encryptedNotice.value = false
    pendingRetry = null
    importOpen.value = false
    importFile.value = null
    importDryRun.value = false
    importing.value = false
    importError.value = ''
    importReport.value = null
    pendingSnapshot = null
    conversations.value = []
    conversationsError.value = ''
    activeConversationId.value = ''
    notes.value = []
    notesTotal.value = 0
    notesPage.value = 1
    notesLoaded.value = false
    notesError.value = ''
    noteFilters.q = ''
    noteFilters.tag = ''
    noteViewerOpen.value = false
    noteDeleteOpen.value = false
    memories.value = []
    memoryTotal.value = 0
    memoryPage.value = 1
    memoryLoaded.value = false
    memoryError.value = ''
    memoryFilters.q = ''
    memoryFilters.kind = ''
    editorOpen.value = false
    editingId.value = null
    deleteOpen.value = false
    exportConfirmOpen.value = false
  }

  async function initialize(): Promise<void> {
    if (!botId.value) return
    resetState()
    await loadConversations()
  }

  watch(
    () => visible.value,
    (show) => {
      if (show) void initialize()
    },
    { immediate: true },
  )

  watch(
    () => botId.value,
    () => {
      if (visible.value) void initialize()
    },
  )

  watch(activeTab, (tab) => {
    if (tab === 'memories' && !memoryLoaded.value) void loadMemories(1)
    if (tab === 'notes' && !notesLoaded.value) void loadNotes(1)
  })

  return {
    // shared
    isNarrow,
    botId,
    activeTab,
    contentConfirmed,
    confirmationOpen,
    confirmationMessage,
    cancelled,
    encryptedNotice,
    confirmContentAccess,
    cancelContentAccess,
    // conversations
    conversations,
    conversationsLoading,
    conversationsError,
    activeConversationId,
    loadConversations,
    selectConversation,
    // memories
    memories,
    memoryTotal,
    memoryPage,
    memoryPageSize,
    memoryLoading,
    memoryError,
    memoryFilters,
    loadMemories,
    applyMemoryFilters,
    resetMemoryFilters,
    // notes
    notes,
    notesTotal,
    notesPage,
    notesPageSize,
    notesLoading,
    notesError,
    noteFilters,
    noteViewerOpen,
    selectedNote,
    noteRead,
    noteReadContent,
    noteReadError,
    noteReadMore,
    noteDeleteOpen,
    noteDeleteTarget,
    noteDeleting,
    loadNotes,
    applyNoteFilters,
    resetNoteFilters,
    openNoteViewer,
    loadMoreNote,
    askDeleteNote,
    confirmDeleteNote,
    // editor
    editorOpen,
    editingId,
    editorError,
    metadataError,
    saving,
    editor,
    openEditor,
    saveEditor,
    // delete
    deleteOpen,
    deleteTarget,
    deleting,
    askDelete,
    confirmDelete,
    // export / import
    exportConfirmOpen,
    exporting,
    importOpen,
    importFile,
    importDryRun,
    importing,
    importError,
    importReport,
    openImport,
    onImportFileChange,
    confirmExport,
    submitImport,
    // shell
    resetState,
    initialize,
  }
}

export type AdminContentContext = ReturnType<typeof useAdminContent>

const ADMIN_CONTENT_KEY: InjectionKey<AdminContentContext> = Symbol('admin-content')

/** 父组件（AdminContentDrawer）调用：向子组件下发共享上下文。 */
export function provideAdminContent(context: AdminContentContext): void {
  provide(ADMIN_CONTENT_KEY, context)
}

/** 子组件调用：读取 AdminContentDrawer 下发的共享上下文。 */
export function useAdminContentContext(): AdminContentContext {
  const context = inject(ADMIN_CONTENT_KEY)
  if (!context) {
    throw new Error('useAdminContentContext() 必须在 AdminContentDrawer 内部使用')
  }
  return context
}
