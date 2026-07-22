import { Controller } from '@hotwired/stimulus'
import { renderStreamMessage } from '@hotwired/turbo'

const FILL_BUFFER_PX = 600
const PREFETCH_ROOT_MARGIN = '500px 0px'
const SCROLL_FALLBACK_PX = 1000
const MAX_FILL_PAGES = 20
const MAX_TRANSIENT_RETRIES = 3
const RETRY_BASE_MS = 400
const BACK_TO_TOP_SHOW_PX = 800

/** Soft cap on rows kept in the document. */
const MAX_ROWS_IN_DOM = 30
/** Rows of buffer above the viewport that must never be pruned. */
const KEEP_BUFFER_PX = 800
/** Complete rows loaded per infinite-scroll fetch after first paint. */
const ROWS_PER_FETCH = 6

/**
 * Infinite scroll for a card grid via Turbo Streams.
 *
 * CSS owns layout: card-sized auto-fill tracks on .browse-card-grid.
 * Cards are always direct children. This controller fetches pages and may
 * prune complete rows from the top (never a partial row) with scroll
 * compensation so visible cards do not reflow.
 */
export default class extends Controller {
  static targets = ['sentinel', 'status', 'backToTop', 'grid']
  static values = {
    nextUrl: { type: String, default: '' },
    perPage: { type: Number, default: 48 },
    sentinelId: { type: String, default: 'models-scroll-sentinel' },
    cardSelector: { type: String, default: '.model-card' },
    storageKeyPrefix: { type: String, default: 'scroll_models_' }
  }

  declare nextUrlValue: string
  declare perPageValue: number
  declare sentinelIdValue: string
  declare cardSelectorValue: string
  declare storageKeyPrefixValue: string
  declare sentinelTarget: HTMLElement
  declare hasSentinelTarget: boolean
  declare statusTarget: HTMLElement
  declare hasStatusTarget: boolean
  declare backToTopTarget: HTMLElement
  declare hasBackToTopTarget: boolean
  declare gridTarget: HTMLElement
  declare hasGridTarget: boolean

  private loading = false
  private exhausted = false
  private observer: IntersectionObserver | null = null
  private observedSentinel: HTMLElement | null = null
  private resizeObserver: ResizeObserver | null = null
  private boundOnScroll: () => void
  private boundOnBeforeVisit: () => void
  private boundOnBackToTop: (e: Event) => void
  private scrollTicking = false
  private abortController: AbortController | null = null
  private lastLoadedUrl = ''
  private transientFailures = 0
  private restoredScroll = false
  /** Live column count from the first grid row; invalidated on resize. */
  private cachedColumns: number | null = null
  /** Total models loaded from the server (not reduced when pruning). */
  private itemsSeen = 0

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
    this.syncNextUrlFromSentinel()
    this.itemsSeen = this.cards().length
    this.alignFetchUrl()
    this.setupObserver()
    this.setupResizeObserver()
    this.updateStatus('')
    this.updateBackToTop()
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
    this.observedSentinel = null
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    this.abortInFlight()
  }

  /** Turbo replace may recreate the sentinel — re-observe after each load. */
  sentinelTargetConnected (): void {
    this.syncNextUrlFromSentinel()
    this.alignFetchUrl()
    this.setupObserver()
  }

  private get hasMore (): boolean {
    return !this.exhausted && this.nextUrlValue.length > 0
  }

  private sentinelEl (): HTMLElement | null {
    return document.getElementById(this.sentinelIdValue)
  }

  /** Abort only on disconnect / navigation — never to cancel a healthy page fetch. */
  private abortInFlight (): void {
    if (this.abortController != null) {
      this.abortController.abort()
      this.abortController = null
    }
  }

  private async bootstrap (): Promise<void> {
    await this.fillViewport()
    this.restoreScrollIfNeeded()
    this.pruneTopRows()
  }

  private setupResizeObserver (): void {
    this.resizeObserver?.disconnect()
    if (typeof ResizeObserver === 'undefined') return
    this.resizeObserver = new ResizeObserver(() => {
      this.cachedColumns = null
      this.alignFetchUrl()
    })
    this.resizeObserver.observe(this.gridEl())
  }

  private setupObserver (): void {
    const el = this.sentinelEl()
    if (el == null || el.hasAttribute('hidden')) {
      this.observer?.disconnect()
      this.observer = null
      this.observedSentinel = null
      return
    }

    if (this.observer != null && this.observedSentinel === el) return

    this.observer?.disconnect()
    this.observedSentinel = el
    this.observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          void this.loadMore()
        }
      },
      { root: null, rootMargin: PREFETCH_ROOT_MARGIN, threshold: 0 }
    )
    this.observer.observe(el)
  }

  private syncNextUrlFromSentinel (): void {
    const el = this.sentinelEl()
    if (el == null) return
    const fromDom = el.dataset.nextUrl
    if (typeof fromDom === 'string' && fromDom.length > 0) {
      this.nextUrlValue = fromDom
      this.exhausted = false
    } else if (el.hasAttribute('hidden') || el.dataset.hasMore === 'false') {
      this.nextUrlValue = ''
      this.exhausted = true
      this.updateStatus(this.endMessage())
      this.element.classList.add('is-exhausted')
    }
  }

  /**
   * Rewrite nextUrl to offset=itemsSeen and per_page=cols*ROWS_PER_FETCH so each
   * fetch is row-aligned and does not skew page-number offsets.
   */
  private alignFetchUrl (): void {
    if (this.nextUrlValue.length === 0) return
    const cols = this.measureColumns()
    const perPage = Math.min(96, Math.max(12, cols * ROWS_PER_FETCH))
    this.perPageValue = perPage
    try {
      const url = new URL(this.nextUrlValue, window.location.origin)
      url.searchParams.delete('page')
      url.searchParams.set('offset', String(this.itemsSeen))
      url.searchParams.set('per_page', String(perPage))
      this.nextUrlValue = url.pathname + url.search
    } catch {
      // ignore malformed next urls
    }
  }

  private cards (): HTMLElement[] {
    const selector = this.cardSelectorValue || '.model-card'
    return Array.from(this.gridEl().querySelectorAll<HTMLElement>(selector))
  }

  /** Live column count from the first grid row. */
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

  /**
   * Remove complete rows from the top when over MAX_ROWS_IN_DOM and those rows
   * sit well above the viewport. Never removes a partial row.
   */
  private pruneTopRows (): void {
    const cols = this.measureColumns()
    const cards = this.cards()
    const maxCards = cols * MAX_ROWS_IN_DOM
    if (cards.length <= maxCards) return

    const overflow = cards.length - maxCards
    const pruneCeiling = window.scrollY - KEEP_BUFFER_PX
    let safeCards = 0
    for (const card of cards) {
      const bottom = card.offsetTop + card.offsetHeight
      if (bottom > pruneCeiling) break
      safeCards += 1
    }

    const safeRows = Math.floor(safeCards / cols)
    const rowsNeeded = Math.ceil(overflow / cols)
    const rowsToRemove = Math.min(safeRows, rowsNeeded)
    const removeCount = rowsToRemove * cols
    if (removeCount < cols) return

    const first = cards[0]
    const last = cards[removeCount - 1]
    const top = first.getBoundingClientRect().top + window.scrollY
    const bottom = last.getBoundingClientRect().bottom + window.scrollY
    const height = bottom - top
    if (!(height > 0)) return

    const scrollY = window.scrollY
    for (let i = 0; i < removeCount; i++) {
      cards[i].remove()
    }
    window.scrollTo(0, Math.max(0, scrollY - height))
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

  private clearLoadingUi (): void {
    this.gridEl().classList.remove('is-loading-more')
    if (!this.exhausted) this.updateStatus('')
  }

  private async fillViewport (): Promise<void> {
    let guard = 0
    while (guard < MAX_FILL_PAGES && this.hasMore && !this.viewportSatisfied()) {
      guard += 1
      const ok = await this.loadMore()
      if (!ok) break
    }
  }

  private gridEl (): HTMLElement {
    return this.hasGridTarget ? this.gridTarget : this.element
  }

  private viewportSatisfied (): boolean {
    const bottom = this.gridEl().getBoundingClientRect().bottom
    return bottom > window.innerHeight + FILL_BUFFER_PX
  }

  private nearBottom (): boolean {
    const scrollBottom = window.scrollY + window.innerHeight
    const docHeight = document.documentElement.scrollHeight
    return docHeight - scrollBottom < SCROLL_FALLBACK_PX
  }

  private async loadMore (): Promise<boolean> {
    // Single-flight: never abort a healthy in-flight page fetch to start another.
    if (this.loading || !this.hasMore) return false

    this.alignFetchUrl()
    const url = this.nextUrlValue
    if (url.length === 0 || url === this.lastLoadedUrl) return false

    this.loading = true
    this.gridEl().classList.add('is-loading-more')
    // Status stays empty while loading — sentinel CSS label shows "Loading more…".
    this.updateStatus('')
    this.abortController = new AbortController()

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
          this.exhausted = true
          this.nextUrlValue = ''
          this.updateStatus(this.endMessage())
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
        this.exhausted = true
        this.nextUrlValue = ''
        this.updateStatus('')
        return false
      }

      this.lastLoadedUrl = url
      this.transientFailures = 0
      const beforeCount = this.cards().length
      renderStreamMessage(html)
      this.dedupeCards()
      const afterCount = this.cards().length
      const added = Math.max(0, afterCount - beforeCount)
      this.itemsSeen += added
      this.cachedColumns = null

      this.syncNextUrlFromSentinel()
      this.alignFetchUrl()
      this.setupObserver()
      this.pruneTopRows()

      if (added === 0) {
        this.exhausted = true
        this.nextUrlValue = ''
        this.updateStatus(this.endMessage())
        this.element.classList.add('is-exhausted')
        return true
      }

      if (!this.hasMore) {
        this.exhausted = true
        this.updateStatus(this.endMessage())
        this.element.classList.add('is-exhausted')
      } else {
        this.updateStatus('')
        this.element.classList.remove('is-exhausted')
      }

      return true
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') {
        this.clearLoadingUi()
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
    this.gridEl().querySelectorAll<HTMLElement>(`${selector}[id]`).forEach((card) => {
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

  private onScroll (): void {
    if (!this.scrollTicking) {
      this.scrollTicking = true
      requestAnimationFrame(() => {
        this.scrollTicking = false
        this.updateBackToTop()
        this.pruneTopRows()
        if (this.nearBottom()) {
          void this.loadMore()
        }
      })
    }
  }

  private updateBackToTop (): void {
    if (!this.hasBackToTopTarget) return
    const show = window.scrollY > BACK_TO_TOP_SHOW_PX
    this.backToTopTarget.toggleAttribute('hidden', !show)
    this.backToTopTarget.classList.toggle('is-visible', show)
  }

  /**
   * Pruned cards above are gone — reload page 1 so the top is complete.
   */
  private onBackToTop (e: Event): void {
    e.preventDefault()
    const url = new URL(window.location.href)
    url.searchParams.delete('page')
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
    if (!url.searchParams.has('page')) return
    url.searchParams.delete('page')
    history.replaceState(history.state, '', url.toString())
  }

  private onBeforeVisit (): void {
    this.persistScrollY()
    this.abortInFlight()
  }

  private storageKey (): string {
    const url = new URL(window.location.href)
    url.searchParams.delete('page')
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
      this.pruneTopRows()
    })
  }
}
