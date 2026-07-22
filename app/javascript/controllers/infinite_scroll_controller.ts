import { Controller } from '@hotwired/stimulus'
import { renderStreamMessage } from '@hotwired/turbo'

const PREFETCH_ROOT_MARGIN = '400px 0px'
const SCROLL_EDGE_PX = 800
const MAX_FILL_ROUNDS = 24
const MAX_TRANSIENT_RETRIES = 3
const RETRY_BASE_MS = 400
const BACK_TO_TOP_SHOW_PX = 800
const MIN_ROWS = 8
const MAX_ROWS = 20
const ROW_HEIGHT_FALLBACK = 280
const BUFFER_ROWS = 4

/**
 * Bidirectional row-window infinite scroll for a card grid.
 *
 * CSS owns layout (card-sized auto-fill). This controller keeps a sliding
 * window of cols×rows cards: scroll down appends one row and drops one from
 * the top; scroll up prepends one row and drops one from the bottom.
 * End-of-list only when the window covers the true end of the result set.
 */
export default class extends Controller {
  static targets = ['sentinel', 'topSentinel', 'status', 'backToTop', 'grid']
  static values = {
    perPage: { type: Number, default: 48 },
    sentinelId: { type: String, default: 'models-scroll-sentinel' },
    topSentinelId: { type: String, default: 'models-scroll-sentinel-top' },
    cardSelector: { type: String, default: '.model-card' },
    storageKeyPrefix: { type: String, default: 'scroll_models_' },
    totalCount: { type: Number, default: 0 },
    windowStart: { type: Number, default: 0 }
  }

  declare perPageValue: number
  declare sentinelIdValue: string
  declare topSentinelIdValue: string
  declare cardSelectorValue: string
  declare storageKeyPrefixValue: string
  declare totalCountValue: number
  declare windowStartValue: number
  declare sentinelTarget: HTMLElement
  declare hasSentinelTarget: boolean
  declare topSentinelTarget: HTMLElement
  declare hasTopSentinelTarget: boolean
  declare statusTarget: HTMLElement
  declare hasStatusTarget: boolean
  declare backToTopTarget: HTMLElement
  declare hasBackToTopTarget: boolean
  declare gridTarget: HTMLElement
  declare hasGridTarget: boolean

  private loading = false
  private mutating = false
  private hasMoreAfter = true
  private hasMoreBefore = false
  private cols = 1
  private rows = MIN_ROWS
  private windowSize = MIN_ROWS
  private cachedColumns: number | null = null
  private observer: IntersectionObserver | null = null
  private resizeObserver: ResizeObserver | null = null
  private mutationObserver: MutationObserver | null = null
  private boundOnScroll: () => void
  private boundOnBeforeVisit: () => void
  private boundOnBackToTop: (e: Event) => void
  private scrollTicking = false
  private abortController: AbortController | null = null
  private transientFailures = 0
  private restoredScroll = false
  private refillQueued = false

  connect (): void {
    this.boundOnScroll = this.onScroll.bind(this)
    this.boundOnBeforeVisit = this.onBeforeVisit.bind(this)
    this.boundOnBackToTop = this.onBackToTop.bind(this)
    window.addEventListener('scroll', this.boundOnScroll, { passive: true })
    document.addEventListener('turbo:before-visit', this.boundOnBeforeVisit)
    if (this.hasBackToTopTarget) {
      this.backToTopTarget.addEventListener('click', this.boundOnBackToTop)
    }

    this.stripPageFromUrl()
    this.syncMetaFromSentinels()
    this.recomputeWindowSize()
    this.refreshBounds()
    this.setupObserver()
    this.setupResizeObserver()
    this.setupMutationObserver()
    this.updateStatus('')
    this.updateBackToTop()
    this.updateExhaustionUi()
    void this.bootstrap()
  }

  disconnect (): void {
    window.removeEventListener('scroll', this.boundOnScroll)
    document.removeEventListener('turbo:before-visit', this.boundOnBeforeVisit)
    if (this.hasBackToTopTarget) {
      this.backToTopTarget.removeEventListener('click', this.boundOnBackToTop)
    }
    this.observer?.disconnect()
    this.observer = null
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    this.mutationObserver?.disconnect()
    this.mutationObserver = null
    this.abortInFlight()
  }

  sentinelTargetConnected (): void {
    this.syncMetaFromSentinels()
    this.refreshBounds()
    this.setupObserver()
    this.updateExhaustionUi()
  }

  topSentinelTargetConnected (): void {
    this.syncMetaFromSentinels()
    this.refreshBounds()
    this.setupObserver()
  }

  private abortInFlight (): void {
    if (this.abortController != null) {
      this.abortController.abort()
      this.abortController = null
    }
  }

  private async bootstrap (): Promise<void> {
    await this.fillOrTrimWindow()
    this.restoreScrollIfNeeded()
    this.updateExhaustionUi()
  }

  private setupResizeObserver (): void {
    this.resizeObserver?.disconnect()
    if (typeof ResizeObserver === 'undefined') return
    this.resizeObserver = new ResizeObserver(() => {
      this.cachedColumns = null
      const prevSize = this.windowSize
      this.recomputeWindowSize()
      if (this.windowSize !== prevSize) {
        void this.fillOrTrimWindow()
      }
    })
    this.resizeObserver.observe(this.gridEl())
  }

  private setupMutationObserver (): void {
    this.mutationObserver?.disconnect()
    if (typeof MutationObserver === 'undefined') return
    this.mutationObserver = new MutationObserver((records) => {
      if (this.mutating || this.loading) return
      let removedCard = false
      for (const record of records) {
        record.removedNodes.forEach((node) => {
          if (!(node instanceof HTMLElement)) return
          if (node.matches?.(this.cardSelectorValue) || node.querySelector?.(this.cardSelectorValue)) {
            removedCard = true
          }
        })
      }
      if (removedCard) {
        this.queueRefill()
      }
    })
    this.mutationObserver.observe(this.gridEl(), { childList: true, subtree: false })
  }

  private queueRefill (): void {
    if (this.refillQueued) return
    this.refillQueued = true
    requestAnimationFrame(() => {
      this.refillQueued = false
      void this.refillOneAfterDelete()
    })
  }

  private setupObserver (): void {
    this.observer?.disconnect()
    this.observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const el = entry.target as HTMLElement
          if (el.id === this.sentinelIdValue || el === this.bottomSentinelEl()) {
            void this.fetchRow('after')
          } else if (el.id === this.topSentinelIdValue || el === this.topSentinelEl()) {
            void this.fetchRow('before')
          }
        }
      },
      { root: null, rootMargin: PREFETCH_ROOT_MARGIN, threshold: 0 }
    )
    const bottom = this.bottomSentinelEl()
    const top = this.topSentinelEl()
    if (bottom != null && this.hasMoreAfter) this.observer.observe(bottom)
    if (top != null && this.hasMoreBefore) this.observer.observe(top)
  }

  private bottomSentinelEl (): HTMLElement | null {
    return document.getElementById(this.sentinelIdValue)
  }

  private topSentinelEl (): HTMLElement | null {
    return document.getElementById(this.topSentinelIdValue)
  }

  private syncMetaFromSentinels (): void {
    const bottom = this.bottomSentinelEl()
    const top = this.topSentinelEl()
    const el = bottom ?? top
    if (el == null) return

    const totalRaw = el.dataset.totalCount
    if (totalRaw != null && totalRaw.length > 0) {
      const total = parseInt(totalRaw, 10)
      if (Number.isFinite(total) && total >= 0) {
        this.totalCountValue = total
      }
    }
  }

  private refreshBounds (): void {
    const count = this.cards().length
    if (this.totalCountValue > 0) {
      this.hasMoreAfter = this.windowStartValue + count < this.totalCountValue
      this.hasMoreBefore = this.windowStartValue > 0
    } else {
      const bottom = this.bottomSentinelEl()
      const top = this.topSentinelEl()
      this.hasMoreAfter = bottom?.dataset.hasMoreAfter === 'true'
      this.hasMoreBefore = this.windowStartValue > 0 || top?.dataset.hasMoreBefore === 'true'
    }
  }

  private cards (): HTMLElement[] {
    const selector = this.cardSelectorValue || '.model-card'
    return Array.from(this.gridEl().querySelectorAll<HTMLElement>(`:scope > ${selector}`))
  }

  private measureColumns (): number {
    if (this.cachedColumns != null && this.cachedColumns > 0) {
      return this.cachedColumns
    }
    const cards = this.cards()
    if (cards.length === 0) {
      this.cachedColumns = 1
      return 1
    }
    const y0 = cards[0].offsetTop
    let cols = 0
    for (const card of cards) {
      if (card.offsetTop !== y0) break
      cols += 1
    }
    this.cachedColumns = Math.max(1, cols)
    return this.cachedColumns
  }

  private measureRows (): number {
    const cards = this.cards()
    let rowHeight = ROW_HEIGHT_FALLBACK
    if (cards.length > 0) {
      const first = cards[0]
      const gap = this.readGap()
      rowHeight = Math.max(80, first.offsetHeight + gap)
    }
    const viewportRows = Math.ceil(window.innerHeight / rowHeight) + BUFFER_ROWS
    return Math.min(MAX_ROWS, Math.max(MIN_ROWS, viewportRows))
  }

  private readGap (): number {
    const style = getComputedStyle(this.gridEl())
    const gap = parseFloat(style.rowGap || style.gap || '0')
    return Number.isFinite(gap) ? gap : 0
  }

  private recomputeWindowSize (): void {
    this.cols = this.measureColumns()
    this.rows = this.measureRows()
    this.windowSize = this.cols * this.rows
    this.perPageValue = this.cols
  }

  private async fillOrTrimWindow (): Promise<void> {
    this.recomputeWindowSize()
    this.refreshBounds()

    let cards = this.cards()
    if (cards.length > this.windowSize) {
      // Prefer dropping the bottom so windowStart (and visible top) stay stable.
      this.trimBottomToWindow()
      cards = this.cards()
    }

    let guard = 0
    while (
      guard < MAX_FILL_ROUNDS &&
      this.cards().length < this.windowSize &&
      this.hasMoreAfter
    ) {
      guard += 1
      const need = this.windowSize - this.cards().length
      const limit = Math.ceil(need / this.cols) * this.cols
      const ok = await this.fetchCards(limit, 'after')
      if (!ok) break
      this.refreshBounds()
    }

    if (this.cards().length > this.windowSize) {
      this.trimBottomToWindow()
    }

    this.setupObserver()
    this.updateExhaustionUi()
  }

  private trimBottomToWindow (): void {
    const excess = this.cards().length - this.windowSize
    if (excess <= 0) return
    const rowsToDrop = Math.floor(excess / this.cols)
    if (rowsToDrop < 1) return
    this.dropRows('bottom', rowsToDrop)
    this.refreshBounds()
  }

  /**
   * After append/prepend, keep at most windowSize cards by dropping complete
   * rows from the opposite end.
   */
  private maintainWindow (direction: 'after' | 'before'): void {
    const excess = this.cards().length - this.windowSize
    if (excess <= 0) return
    const rowsToDrop = Math.floor(excess / this.cols)
    if (rowsToDrop < 1) return

    if (direction === 'after') {
      this.dropRows('top', rowsToDrop)
      this.windowStartValue += rowsToDrop * this.cols
    } else {
      this.dropRows('bottom', rowsToDrop)
    }
    this.refreshBounds()
  }

  private dropRows (side: 'top' | 'bottom', rowCount: number): void {
    const cols = this.cols
    const removeCount = rowCount * cols
    if (removeCount < 1) return

    const cards = this.cards()
    if (cards.length < removeCount) return

    const slice = side === 'top'
      ? cards.slice(0, removeCount)
      : cards.slice(cards.length - removeCount)

    let height = 0
    if (side === 'top' && slice.length > 0) {
      const first = slice[0]
      const last = slice[slice.length - 1]
      const top = first.getBoundingClientRect().top + window.scrollY
      const bottom = last.getBoundingClientRect().bottom + window.scrollY
      height = Math.max(0, bottom - top)
    }

    this.mutating = true
    try {
      const scrollY = window.scrollY
      for (const card of slice) {
        card.remove()
      }
      if (side === 'top' && height > 0) {
        window.scrollTo(0, Math.max(0, scrollY - height))
      }
    } finally {
      this.mutating = false
    }
  }

  private buildFetchUrl (offset: number, limit: number, windowDir: 'before' | 'after'): string {
    const url = new URL(window.location.href)
    url.searchParams.delete('page')
    url.searchParams.set('offset', String(Math.max(0, offset)))
    url.searchParams.set('per_page', String(Math.max(1, limit)))
    url.searchParams.set('window', windowDir)
    return url.pathname + url.search
  }

  private async fetchRow (direction: 'after' | 'before'): Promise<boolean> {
    this.recomputeWindowSize()
    this.refreshBounds()

    if (direction === 'after') {
      if (!this.hasMoreAfter) {
        this.updateExhaustionUi()
        return false
      }
      return await this.fetchCards(this.cols, 'after')
    }

    if (!this.hasMoreBefore || this.windowStartValue <= 0) {
      return false
    }
    const limit = Math.min(this.cols, this.windowStartValue)
    return await this.fetchCards(limit, 'before')
  }

  private async refillOneAfterDelete (): Promise<void> {
    this.refreshBounds()
    if (!this.hasMoreAfter || this.loading) return
    // Keep window full until true end; do not change windowStart on middle delete.
    if (this.cards().length >= this.windowSize) return
    await this.fetchCards(1, 'after')
    this.updateExhaustionUi()
  }

  private async fetchCards (limit: number, direction: 'after' | 'before'): Promise<boolean> {
    if (this.loading) return false

    const offset = direction === 'after'
      ? this.windowStartValue + this.cards().length
      : Math.max(0, this.windowStartValue - limit)

    if (direction === 'before' && this.windowStartValue <= 0) return false
    if (direction === 'after' && this.totalCountValue > 0 && offset >= this.totalCountValue) {
      this.hasMoreAfter = false
      this.updateExhaustionUi()
      return false
    }

    const url = this.buildFetchUrl(offset, limit, direction)

    this.loading = true
    this.gridEl().classList.add('is-loading-more')
    this.updateStatus('')
    this.abortController = new AbortController()

    const anchor = direction === 'before' ? this.cards()[0] : null
    const anchorTop = anchor?.getBoundingClientRect().top ?? 0

    try {
      const response = await fetch(url, {
        headers: {
          Accept: 'text/vnd.turbo-stream.html',
          'X-Infinite-Scroll': '1'
        },
        credentials: 'same-origin',
        signal: this.abortController.signal
      })

      if (!response.ok) {
        console.warn('[infinite-scroll] HTTP', response.status, url)
        if (response.status === 401 || response.status === 403 || response.status === 404) {
          this.hasMoreAfter = false
          this.updateExhaustionUi()
          return false
        }
        this.transientFailures += 1
        if (this.transientFailures >= MAX_TRANSIENT_RETRIES) {
          this.updateStatus('Could not load more. Scroll to retry.')
          this.transientFailures = 0
        } else {
          await this.delay(RETRY_BASE_MS * this.transientFailures)
        }
        return false
      }

      const contentType = response.headers.get('Content-Type') ?? ''
      const html = await response.text()

      if (!contentType.includes('turbo-stream') && !html.includes('<turbo-stream')) {
        console.warn('[infinite-scroll] expected turbo-stream, got', contentType.slice(0, 80))
        return false
      }

      this.transientFailures = 0
      const beforeCount = this.cards().length

      this.mutating = true
      try {
        renderStreamMessage(html)
        this.dedupeCards()
      } finally {
        this.mutating = false
      }

      const afterCount = this.cards().length
      const added = Math.max(0, afterCount - beforeCount)
      this.cachedColumns = null
      this.recomputeWindowSize()
      this.syncMetaFromSentinels()

      if (direction === 'before' && added > 0) {
        this.windowStartValue = offset
        if (anchor != null && document.contains(anchor)) {
          const delta = anchor.getBoundingClientRect().top - anchorTop
          if (delta !== 0) {
            window.scrollBy(0, delta)
          }
        }
        this.maintainWindow('before')
      } else if (direction === 'after' && added > 0) {
        this.maintainWindow('after')
      }

      // Empty batch alone is not end-of-list; only totalCount bounds matter.
      this.refreshBounds()
      this.setupObserver()
      this.updateExhaustionUi()
      return added > 0 || !this.hasMoreAfter
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') {
        return false
      }
      console.warn('[infinite-scroll] load error', e)
      this.transientFailures += 1
      this.updateStatus('Could not load more. Scroll to retry.')
      return false
    } finally {
      this.loading = false
      this.gridEl().classList.remove('is-loading-more')
      this.abortController = null
    }
  }

  private dedupeCards (): void {
    const selector = this.cardSelectorValue || '.model-card'
    const seen = new Set<string>()
    this.gridEl().querySelectorAll<HTMLElement>(`:scope > ${selector}[id]`).forEach((card) => {
      if (seen.has(card.id)) {
        card.remove()
      } else {
        seen.add(card.id)
      }
    })
  }

  private delay (ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  private endMessage (): string {
    return this.element.getAttribute('data-infinite-scroll-end-message-value') ||
      'End of results'
  }

  private updateStatus (text: string): void {
    if (!this.hasStatusTarget) return
    this.statusTarget.textContent = text
    if (text.length > 0) {
      this.statusTarget.removeAttribute('hidden')
    } else {
      this.statusTarget.setAttribute('hidden', 'hidden')
    }
  }

  /** End message only when the window covers the true end of the result set. */
  private updateExhaustionUi (): void {
    this.refreshBounds()
    if (!this.hasMoreAfter) {
      this.element.classList.add('is-exhausted')
      // Show once the true end is in the window (short lists or scrolled to last row).
      this.updateStatus(this.endMessage())
    } else {
      this.element.classList.remove('is-exhausted')
      this.updateStatus('')
    }
  }

  private nearBottom (): boolean {
    const scrollBottom = window.scrollY + window.innerHeight
    const docHeight = document.documentElement.scrollHeight
    return docHeight - scrollBottom < SCROLL_EDGE_PX
  }

  private nearTop (): boolean {
    return window.scrollY < SCROLL_EDGE_PX
  }

  private onScroll (): void {
    if (!this.scrollTicking) {
      this.scrollTicking = true
      requestAnimationFrame(() => {
        this.scrollTicking = false
        this.updateBackToTop()
        if (this.nearBottom() && this.hasMoreAfter) {
          void this.fetchRow('after')
        } else if (this.nearTop() && this.hasMoreBefore) {
          void this.fetchRow('before')
        }
        this.updateExhaustionUi()
      })
    }
  }

  private updateBackToTop (): void {
    if (!this.hasBackToTopTarget) return
    const show = window.scrollY > BACK_TO_TOP_SHOW_PX
    this.backToTopTarget.toggleAttribute('hidden', !show)
    this.backToTopTarget.classList.toggle('is-visible', show)
  }

  /** Jump to true start of the list (reload page 1 window). */
  private onBackToTop (e: Event): void {
    e.preventDefault()
    const url = new URL(window.location.href)
    url.searchParams.delete('page')
    url.searchParams.delete('offset')
    url.searchParams.delete('per_page')
    url.searchParams.delete('window')
    const path = url.pathname + url.search
    const turbo = (window as unknown as { Turbo?: { visit: (loc: string) => void } }).Turbo
    if (turbo?.visit != null) {
      turbo.visit(path)
    } else {
      window.location.assign(path)
    }
  }

  private stripPageFromUrl (): void {
    const url = new URL(window.location.href)
    let changed = false
    for (const key of ['page', 'offset', 'per_page', 'window']) {
      if (url.searchParams.has(key)) {
        url.searchParams.delete(key)
        changed = true
      }
    }
    if (changed) {
      history.replaceState(history.state, '', url.toString())
    }
  }

  private onBeforeVisit (): void {
    this.persistScrollY()
    this.abortInFlight()
  }

  private storageKey (): string {
    const url = new URL(window.location.href)
    for (const key of ['page', 'offset', 'per_page', 'window']) {
      url.searchParams.delete(key)
    }
    const q = url.searchParams.toString()
    return this.storageKeyPrefixValue + url.pathname + (q.length > 0 ? `?${q}` : '')
  }

  private persistScrollY (): void {
    try {
      sessionStorage.setItem(this.storageKey(), String(Math.round(window.scrollY)))
    } catch {
      // private mode / quota
    }
  }

  private restoreScrollIfNeeded (): void {
    if (this.restoredScroll) return
    this.restoredScroll = true
    let y = 0
    try {
      const raw = sessionStorage.getItem(this.storageKey())
      if (raw == null) return
      y = parseInt(raw, 10)
      sessionStorage.removeItem(this.storageKey())
    } catch {
      return
    }
    if (!Number.isFinite(y) || y < 1) return
    requestAnimationFrame(() => {
      window.scrollTo(0, y)
      this.updateBackToTop()
    })
  }

  private gridEl (): HTMLElement {
    return this.hasGridTarget ? this.gridTarget : this.element
  }
}
