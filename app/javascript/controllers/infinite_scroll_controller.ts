import { Controller } from '@hotwired/stimulus'
import { renderStreamMessage } from '@hotwired/turbo'

const FILL_BUFFER_PX = 600
const PREFETCH_ROOT_MARGIN = '500px 0px'
const SCROLL_FALLBACK_PX = 1000
const MAX_FILL_PAGES = 20
const MAX_TRANSIENT_RETRIES = 3
const RETRY_BASE_MS = 400
const BACK_TO_TOP_SHOW_PX = 800
const DEFAULT_GAP_PX = 14
const DEFAULT_ROW_HEIGHT_PX = 320

type BufferedCard = { id: string, html: string }

/**
 * Infinite scroll for a card grid via Turbo Streams.
 *
 * GET next page with Accept: text/vnd.turbo-stream.html
 * Server inserts cards before the sentinel and replaces the sentinel.
 *
 * When virtualize=true (models), only a viewport+overscan window stays in the DOM;
 * loaded cards live in a logical buffer. Near the buffer end, next-page fetch continues.
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
  private virtualWindowStart = 0

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
      this.ensureMetrics()
      this.applyVirtualWindow()
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
    this.observer?.disconnect()
    const el = this.sentinelEl()
    if (el == null || el.hasAttribute('hidden')) return

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

  private async loadMore (): Promise<boolean> {
    if (this.loading || !this.hasMore) return false

    const url = this.nextUrlValue
    if (url.length === 0 || url === this.lastLoadedUrl) return false

    this.loading = true
    this.gridEl().classList.add('is-loading-more')
    this.updateStatus('Loading more…')
    this.abortInFlight()
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
        this.ensureMetrics()
        this.applyVirtualWindow()
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
      if ((e as Error)?.name === 'AbortError') return false
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
    this.harvestCardsFromDom()
  }

  private harvestCardsFromDom (): void {
    const selector = this.cardSelectorValue || '.model-card'
    const cards = Array.from(
      this.gridEl().querySelectorAll<HTMLElement>(`${selector}[id]`)
    )
    cards.forEach((card) => {
      if (!this.bufferIds.has(card.id)) {
        this.cardBuffer.push({ id: card.id, html: card.outerHTML })
        this.bufferIds.add(card.id)
      }
      card.remove()
    })
  }

  private ensureMetrics (): void {
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

    // Measure from a temporary sample if buffer has HTML; else keep default.
    if (this.cardBuffer.length > 0 && !this.metricsReady) {
      const probe = document.createElement('div')
      probe.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none;width:100%'
      probe.innerHTML = this.cardBuffer[0].html
      grid.appendChild(probe)
      const sample = probe.firstElementChild as HTMLElement | null
      if (sample != null) {
        const h = sample.getBoundingClientRect().height
        if (h > 40) {
          this.rowHeight = h + this.gapPx
          this.metricsReady = true
        }
      }
      probe.remove()
    }

    // Prefer live card if window already rendered.
    const live = grid.querySelector<HTMLElement>(this.cardSelectorValue)
    if (live != null) {
      const h = live.getBoundingClientRect().height
      if (h > 40) {
        this.rowHeight = h + this.gapPx
        this.metricsReady = true
      }
    }
  }

  private applyVirtualWindow (): void {
    if (!this.virtualizeValue) return
    const grid = this.gridEl()
    const sentinel = this.sentinelEl()
    if (sentinel == null) return

    this.ensureMetrics()
    const cols = Math.max(1, this.cols)
    const total = this.cardBuffer.length
    const totalRows = Math.ceil(total / cols)
    const rowH = this.rowHeight

    const gridRect = grid.getBoundingClientRect()
    const gridTopDoc = gridRect.top + window.scrollY
    const viewTop = Math.max(0, window.scrollY - gridTopDoc)
    const viewBottom = viewTop + window.innerHeight

    const startRow = Math.max(0, Math.floor(viewTop / rowH) - this.overscanRowsValue)
    const endRow = Math.min(totalRows, Math.ceil(viewBottom / rowH) + this.overscanRowsValue)
    const startIdx = startRow * cols
    const endIdx = Math.min(total, endRow * cols)
    this.virtualWindowStart = startIdx

    // Remove current window cards + spacers (keep sentinel + unassigned tiles).
    grid.querySelectorAll<HTMLElement>(`${this.cardSelectorValue}[id]`).forEach((el) => el.remove())
    grid.querySelectorAll('.browse-virtual-top-spacer, .browse-virtual-bottom-spacer').forEach((el) => el.remove())

    const topSpacer = document.createElement('div')
    topSpacer.className = 'browse-virtual-top-spacer'
    topSpacer.setAttribute('aria-hidden', 'true')
    topSpacer.style.height = `${startRow * rowH}px`

    const bottomRows = Math.max(0, totalRows - endRow)
    const bottomSpacer = document.createElement('div')
    bottomSpacer.className = 'browse-virtual-bottom-spacer'
    bottomSpacer.setAttribute('aria-hidden', 'true')
    bottomSpacer.style.cssText = `grid-column:1/-1;width:100%;pointer-events:none;overflow-anchor:none;height:${bottomRows * rowH}px`

    const frag = document.createDocumentFragment()
    frag.appendChild(topSpacer)
    for (let i = startIdx; i < endIdx; i++) {
      const wrap = document.createElement('div')
      wrap.innerHTML = this.cardBuffer[i].html
      const node = wrap.firstElementChild
      if (node != null) frag.appendChild(node)
    }
    frag.appendChild(bottomSpacer)

    grid.insertBefore(frag, sentinel)
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
          this.applyVirtualWindow()
          // Prefetch when the virtual window approaches the end of the buffer.
          const cols = Math.max(1, this.cols)
          const nearBufferEnd =
            this.virtualWindowStart + cols * (this.overscanRowsValue + 6) >= this.cardBuffer.length
          if (nearBufferEnd || this.nearBottom()) {
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
      if (this.virtualizeValue) this.applyVirtualWindow()
      this.updateBackToTop()
    })
  }
}
