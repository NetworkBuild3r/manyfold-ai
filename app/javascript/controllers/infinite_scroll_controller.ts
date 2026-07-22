import { Controller } from '@hotwired/stimulus'
import { renderStreamMessage } from '@hotwired/turbo'

const FILL_BUFFER_PX = 600
const PREFETCH_ROOT_MARGIN = '500px 0px'
const SCROLL_FALLBACK_PX = 1000
const MAX_FILL_PAGES = 20
const MAX_VIRTUAL_FILL_PAGES = 3
const MAX_TRANSIENT_RETRIES = 3
const RETRY_BASE_MS = 400
const BACK_TO_TOP_SHOW_PX = 800
const DEFAULT_GAP_PX = 14
const DEFAULT_ROW_HEIGHT_PX = 360
/** Extra rows past the visible window before we prefetch the next page. */
const BUFFER_PREFETCH_ROWS = 4

type BufferedCard = { id: string, html: string }

/**
 * Infinite scroll for a card grid via Turbo Streams.
 *
 * Virtualize mode (models): cards live in a logical buffer; the DOM keeps a
 * fixed-height shell + translated window grid (not CSS-grid spacers — those
 * desync from real card height and leave a one-row + empty void).
 */
export default class extends Controller {
  static targets = ['sentinel', 'status', 'backToTop', 'grid']
  static values = {
    nextUrl: { type: String, default: '' },
    perPage: { type: Number, default: 24 },
    sentinelId: { type: String, default: 'models-scroll-sentinel' },
    cardSelector: { type: String, default: '.model-card' },
    storageKeyPrefix: { type: String, default: 'scroll_models_' },
    virtualize: { type: Boolean, default: false },
    overscanRows: { type: Number, default: 4 }
  }

  declare nextUrlValue: string
  declare perPageValue: number
  declare sentinelIdValue: string
  declare cardSelectorValue: string
  declare storageKeyPrefixValue: string
  declare virtualizeValue: boolean
  declare overscanRowsValue: number
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
  private boundOnScroll: () => void
  private boundOnBeforeVisit: () => void
  private boundOnBackToTop: (e: Event) => void
  private scrollTicking = false
  private abortController: AbortController | null = null
  private lastLoadedUrl = ''
  private transientFailures = 0
  private restoredScroll = false

  private cardBuffer: BufferedCard[] = []
  private bufferIds = new Set<string>()
  private cols = 3
  private rowHeight = DEFAULT_ROW_HEIGHT_PX
  private gapPx = DEFAULT_GAP_PX
  private metricsReady = false
  private remasurePending = false
  private virtualWindowStart = 0
  private lastAppliedStartIdx = -1
  private lastAppliedEndIdx = -1
  private lastBufferLength = -1
  private windowEl: HTMLElement | null = null

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
    if (this.virtualizeValue) {
      this.seedBufferFromDom()
      this.readColumnMetrics()
      this.ensureVirtualShell()
      this.applyVirtualWindow(true)
      this.scheduleRowHeightRemeasure()
    }
    this.setupObserver()
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
    this.abortInFlight()
  }

  /** Turbo replace may recreate the sentinel — re-observe after each load. */
  sentinelTargetConnected (): void {
    this.syncNextUrlFromSentinel()
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
        if (!entries.some((e) => e.isIntersecting)) return
        if (this.virtualizeValue) {
          if (this.nearBufferEnd()) void this.loadMore()
        } else {
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
    const maxPages = this.virtualizeValue ? MAX_VIRTUAL_FILL_PAGES : MAX_FILL_PAGES
    let guard = 0
    while (guard < maxPages && this.hasMore && !this.viewportSatisfied()) {
      guard += 1
      const ok = await this.loadMore()
      if (!ok) break
    }
  }

  private gridEl (): HTMLElement {
    return this.hasGridTarget ? this.gridTarget : this.element
  }

  private viewportSatisfied (): boolean {
    if (this.virtualizeValue && this.cardBuffer.length > 0) {
      const totalRows = Math.ceil(this.cardBuffer.length / Math.max(1, this.cols))
      const logicalHeight = totalRows * this.rowHeight
      const gridTop = this.gridEl().getBoundingClientRect().top + window.scrollY
      return gridTop + logicalHeight > window.scrollY + window.innerHeight + FILL_BUFFER_PX
    }
    const bottom = this.gridEl().getBoundingClientRect().bottom
    return bottom > window.innerHeight + FILL_BUFFER_PX
  }

  private nearBottom (): boolean {
    const scrollBottom = window.scrollY + window.innerHeight
    const docHeight = document.documentElement.scrollHeight
    return docHeight - scrollBottom < SCROLL_FALLBACK_PX
  }

  /** True when the scroll position (or window) approaches the end of the buffer. */
  private nearBufferEnd (): boolean {
    if (!this.hasMore) return false
    if (this.cardBuffer.length === 0) return true

    const cols = Math.max(1, this.cols)
    const prefetchCards = cols * BUFFER_PREFETCH_ROWS
    if (this.lastAppliedEndIdx >= 0) {
      return this.lastAppliedEndIdx + prefetchCards >= this.cardBuffer.length
    }

    const grid = this.gridEl()
    const gridTop = grid.getBoundingClientRect().top + window.scrollY
    const totalRows = Math.ceil(this.cardBuffer.length / cols)
    const logicalBottom = gridTop + totalRows * this.rowHeight
    return window.scrollY + window.innerHeight >= logicalBottom - BUFFER_PREFETCH_ROWS * this.rowHeight
  }

  private async loadMore (): Promise<boolean> {
    if (this.loading || !this.hasMore) return false

    const url = this.nextUrlValue
    if (url.length === 0 || url === this.lastLoadedUrl) return false

    this.loading = true
    this.gridEl().classList.add('is-loading-more')
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
      renderStreamMessage(html)

      if (this.virtualizeValue) {
        this.harvestCardsFromDom()
        this.ensureVirtualShell()
        this.applyVirtualWindow(true)
        this.scheduleRowHeightRemeasure()
      } else {
        this.dedupeCards()
      }

      this.syncNextUrlFromSentinel()
      this.setupObserver()

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

  private seedBufferFromDom (): void {
    this.cardBuffer = []
    this.bufferIds.clear()
    this.lastAppliedStartIdx = -1
    this.lastAppliedEndIdx = -1
    this.lastBufferLength = -1
    this.harvestCardsFromDom()
  }

  private harvestCardsFromDom (): void {
    const selector = this.cardSelectorValue || '.model-card'
    const grid = this.gridEl()
    const cards = Array.from(grid.querySelectorAll<HTMLElement>(`${selector}[id]`))
    cards.forEach((card) => {
      if (!this.bufferIds.has(card.id)) {
        this.cardBuffer.push({ id: card.id, html: card.outerHTML })
        this.bufferIds.add(card.id)
      }
      card.remove()
    })
  }

  private readColumnMetrics (): void {
    const grid = this.gridEl()
    const fromData = parseInt(grid.dataset.browseColumns || '', 10)
    if (Number.isFinite(fromData) && fromData > 0) {
      this.cols = fromData
    } else {
      const styleCols = getComputedStyle(grid).getPropertyValue('--browse-cols').trim()
      const parsed = parseInt(styleCols, 10)
      if (Number.isFinite(parsed) && parsed > 0) this.cols = parsed
    }

    const gapRaw = getComputedStyle(grid).rowGap || getComputedStyle(grid).gap
    const gapParsed = parseFloat(gapRaw)
    if (Number.isFinite(gapParsed) && gapParsed > 0) this.gapPx = gapParsed

    // Mobile uses 2 columns via grid-cols-2; keep window math aligned below sm.
    if (window.matchMedia('(max-width: 639px)').matches) {
      this.cols = 2
    }
  }

  /**
   * Outer shell: block + explicit height. Inner window: real CSS grid of visible cards.
   * Avoids full-width spacer rows that desync from real card height.
   */
  private ensureVirtualShell (): void {
    const grid = this.gridEl()
    const sentinel = this.sentinelEl()
    grid.classList.add('browse-card-grid--virtual')

    let win = grid.querySelector<HTMLElement>(':scope > .browse-virtual-window')
    if (win == null) {
      win = document.createElement('div')
      win.className = 'browse-virtual-window'
      win.setAttribute('role', 'presentation')
      if (sentinel != null) {
        grid.insertBefore(win, sentinel)
      } else {
        grid.appendChild(win)
      }
    }
    this.windowEl = win
    this.applyWindowGridLayout(win)
  }

  /** Force multi-column tracks — never fall back to full-width stacked cards. */
  private applyWindowGridLayout (win: HTMLElement): void {
    const cols = Math.max(2, this.cols)
    this.cols = cols
    const colsVar = this.gridEl().style.getPropertyValue('--browse-cols') || String(cols)
    win.style.setProperty('--browse-cols', colsVar)
    win.style.display = 'grid'
    win.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`
    win.style.gap = `${this.gapPx}px`
    win.style.alignItems = 'start'
    win.style.width = '100%'
    win.style.boxSizing = 'border-box'
  }

  private scheduleRowHeightRemeasure (): void {
    if (this.remasurePending || !this.virtualizeValue) return
    this.remasurePending = true
    requestAnimationFrame(() => {
      this.remasurePending = false
      const win = this.windowEl
      if (win == null) return
      // Measure only after grid columns are applied (card is cell-width, not full bleed).
      this.applyWindowGridLayout(win)
      const live = win.querySelector<HTMLElement>(this.cardSelectorValue)
      if (live == null) return
      const h = live.getBoundingClientRect().height
      const w = live.getBoundingClientRect().width
      if (h < 40) return
      // Guard: if card is still full-bleed, layout failed — do not lock a giant rowHeight.
      const gridW = this.gridEl().getBoundingClientRect().width
      if (gridW > 0 && w > gridW * 0.8) return
      const next = h + this.gapPx
      if (!this.metricsReady || Math.abs(next - this.rowHeight) > 4) {
        this.rowHeight = next
        this.metricsReady = true
        this.applyVirtualWindow(true)
      }
    })
  }

  /**
   * Render startIdx..endIdx into the translated window; outer height = full buffer.
   */
  private applyVirtualWindow (force = false): void {
    if (!this.virtualizeValue) return
    const grid = this.gridEl()
    const sentinel = this.sentinelEl()
    if (sentinel == null) return

    this.readColumnMetrics()
    this.ensureVirtualShell()
    const win = this.windowEl
    if (win == null) return
    this.applyWindowGridLayout(win)

    const cols = Math.max(2, this.cols)
    this.cols = cols
    const total = this.cardBuffer.length
    const totalRows = Math.max(1, Math.ceil(total / cols) || 1)
    const rowH = this.rowHeight
    const bufferGrew = total !== this.lastBufferLength

    const gridRect = grid.getBoundingClientRect()
    const gridTopDoc = gridRect.top + window.scrollY
    const viewTop = Math.max(0, window.scrollY - gridTopDoc)
    const viewBottom = viewTop + window.innerHeight

    const startRow = Math.max(0, Math.floor(viewTop / rowH) - this.overscanRowsValue)
    const endRow = Math.min(totalRows, Math.ceil(viewBottom / rowH) + this.overscanRowsValue)
    const startIdx = Math.min(total, startRow * cols)
    // Always render at least one full row of cards.
    const endIdx = Math.min(total, Math.max(startIdx + cols, endRow * cols))
    this.virtualWindowStart = startIdx

    if (
      !force &&
      !bufferGrew &&
      startIdx === this.lastAppliedStartIdx &&
      endIdx === this.lastAppliedEndIdx
    ) {
      return
    }

    this.lastAppliedStartIdx = startIdx
    this.lastAppliedEndIdx = endIdx
    this.lastBufferLength = total

    // Outer shell height = full logical list (sentinel sits at the bottom).
    const totalHeight = totalRows * rowH
    grid.style.height = `${Math.max(totalHeight, rowH)}px`

    win.style.transform = `translateY(${startRow * rowH}px)`
    win.replaceChildren()
    for (let i = startIdx; i < endIdx; i++) {
      const wrap = document.createElement('div')
      wrap.innerHTML = this.cardBuffer[i].html
      const node = wrap.firstElementChild as HTMLElement | null
      if (node != null) {
        node.style.minWidth = '0'
        node.style.maxWidth = '100%'
        win.appendChild(node)
      }
    }

    // Keep sentinel as last child of the outer shell for turbo-stream + IO.
    if (sentinel.parentElement !== grid || grid.lastElementChild !== sentinel) {
      grid.appendChild(sentinel)
    }
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
        if (this.virtualizeValue) {
          this.applyVirtualWindow(false)
          if (this.nearBufferEnd()) {
            void this.loadMore()
          }
        } else if (this.nearBottom()) {
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

  private onBackToTop (e: Event): void {
    e.preventDefault()
    window.scrollTo({ top: 0, behavior: 'smooth' })
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
      if (this.virtualizeValue) this.applyVirtualWindow(true)
      this.updateBackToTop()
    })
  }
}
