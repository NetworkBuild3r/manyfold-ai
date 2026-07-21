import { Controller } from '@hotwired/stimulus'
import { renderStreamMessage } from '@hotwired/turbo'

const FILL_BUFFER_PX = 600
const PREFETCH_ROOT_MARGIN = '1400px 0px'
const SCROLL_FALLBACK_PX = 1000
const MAX_FILL_PAGES = 20
const SCROLL_RESTORE_KEY_PREFIX = 'scroll_models_'
const MAX_TRANSIENT_RETRIES = 3
const RETRY_BASE_MS = 400
const BACK_TO_TOP_SHOW_PX = 800
const SPACER_ID = 'models-scroll-spacer'

/**
 * Real infinite scroll for the models grid via Turbo Streams.
 *
 * GET next page with Accept: text/vnd.turbo-stream.html
 * Server inserts a row page-break + cards before #models-scroll-sentinel.
 *
 * Browser URL stays a single infinite browse (no ?page=N). Scroll position is
 * restored via sessionStorage on back navigation. While a page loads we reserve
 * height and pin the first visible card so the viewport does not jump.
 */
export default class extends Controller {
  static targets = ['sentinel', 'status', 'backToTop', 'grid']
  static values = {
    nextUrl: { type: String, default: '' },
    perPage: { type: Number, default: 24 }
  }

  declare nextUrlValue: string
  declare perPageValue: number
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
    this.removeSpacer()
  }

  /** Turbo replace may recreate the sentinel — re-observe after each load. */
  sentinelTargetConnected (): void {
    this.syncNextUrlFromSentinel()
    this.setupObserver()
  }

  private get hasMore (): boolean {
    return !this.exhausted && this.nextUrlValue.length > 0
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
    // Prefer getElementById: turbo_stream.replace recreates the node
    const el = document.getElementById('models-scroll-sentinel')
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
    // Prefer live DOM after turbo_stream.replace
    const el = document.getElementById('models-scroll-sentinel')
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
    // Stimulus maps data-infinite-scroll-end-message-value → endMessageValue when declared;
    // fall back to reading the attribute so we don't need a typed value for i18n text.
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
    // Guard against double-fetch of the same page (IO + scroll race)
    if (url.length === 0 || url === this.lastLoadedUrl) return false

    this.loading = true
    this.gridEl().classList.add('is-loading-more')
    this.updateStatus('Loading more…')
    this.abortInFlight()
    this.abortController = new AbortController()

    const pin = this.captureScrollPin()
    this.insertLoadingSpacer()

    try {
      const response = await fetch(url, {
        headers: {
          Accept: 'text/vnd.turbo-stream.html, text/html',
          'X-Infinite-Scroll': '1'
        },
        credentials: 'same-origin',
        signal: this.abortController.signal
      })

      if (!response.ok) {
        console.warn('[infinite-scroll] HTTP', response.status, url)
        this.removeSpacer()
        if (response.status === 401 || response.status === 403 || response.status === 404) {
          this.exhausted = true
          this.nextUrlValue = ''
          this.updateStatus(this.endMessage())
          return false
        }
        // Transient 5xx / 429 — retry later without permanent exhaust
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
        this.removeSpacer()
        // Full HTML (e.g. login) — stop rather than loop
        this.exhausted = true
        this.nextUrlValue = ''
        this.updateStatus('')
        return false
      }

      this.lastLoadedUrl = url
      this.transientFailures = 0
      renderStreamMessage(html)
      this.removeSpacer()
      this.dedupeModelCards()
      this.restoreScrollPin(pin)

      // After streams: sentinel replaced — read next URL from new node
      this.syncNextUrlFromSentinel()
      // Target may have been recreated; re-bind IO
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
      this.removeSpacer()
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

  /** First visible card + its viewport Y — used to correct jump after DOM insert. */
  private captureScrollPin (): { id: string, top: number } | null {
    const cards = this.gridEl().querySelectorAll<HTMLElement>('.model-card[id]')
    for (const card of Array.from(cards)) {
      const rect = card.getBoundingClientRect()
      if (rect.bottom > 80) {
        return { id: card.id, top: rect.top }
      }
    }
    return null
  }

  private restoreScrollPin (pin: { id: string, top: number } | null): void {
    if (pin == null) return
    const el = document.getElementById(pin.id)
    if (el == null) return
    const delta = el.getBoundingClientRect().top - pin.top
    if (Math.abs(delta) > 1) {
      window.scrollBy(0, delta)
    }
  }

  private columnCount (): number {
    const raw = getComputedStyle(this.gridEl()).gridTemplateColumns
    if (!raw || raw === 'none') return 1
    const cols = raw.split(/\s+/).filter((p) => p.length > 0).length
    return Math.max(1, cols)
  }

  private estimatedPageHeightPx (): number {
    const cards = this.gridEl().querySelectorAll<HTMLElement>('.model-card')
    const sample = cards.length > 0 ? cards[cards.length - 1] : null
    const cardH = sample != null ? sample.getBoundingClientRect().height : 280
    const styles = getComputedStyle(this.gridEl())
    const rowGap = parseFloat(styles.rowGap || styles.gap || '0') || 0
    const cols = this.columnCount()
    const perPage = this.perPageValue > 0 ? this.perPageValue : 24
    const rows = Math.max(1, Math.ceil(perPage / cols))
    return Math.round(rows * (cardH + rowGap))
  }

  private insertLoadingSpacer (): void {
    this.removeSpacer()
    const sentinel = document.getElementById('models-scroll-sentinel')
    if (sentinel == null || sentinel.parentElement == null) return
    const spacer = document.createElement('div')
    spacer.id = SPACER_ID
    spacer.className = 'models-scroll-spacer'
    spacer.setAttribute('aria-hidden', 'true')
    spacer.style.height = `${this.estimatedPageHeightPx()}px`
    sentinel.parentElement.insertBefore(spacer, sentinel)
  }

  private removeSpacer (): void {
    document.getElementById(SPACER_ID)?.remove()
  }

  /** Drop later duplicates if the same model card id already exists in the grid. */
  private dedupeModelCards (): void {
    const seen = new Set<string>()
    this.gridEl().querySelectorAll<HTMLElement>('.model-card[id]').forEach((card) => {
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

  private onBackToTop (e: Event): void {
    e.preventDefault()
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  /** Keep the address bar as one infinite browse — never surface ?page=N. */
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
    // Restore against path + filters, ignore page
    url.searchParams.delete('page')
    const q = url.searchParams.toString()
    return SCROLL_RESTORE_KEY_PREFIX + url.pathname + (q.length > 0 ? `?${q}` : '')
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
    // After fillViewport the document is taller; restore on next frame
    requestAnimationFrame(() => {
      window.scrollTo(0, y)
      this.updateBackToTop()
    })
  }
}
