import { Controller } from '@hotwired/stimulus'
import { renderStreamMessage } from '@hotwired/turbo'

const FILL_BUFFER_PX = 600
const PREFETCH_ROOT_MARGIN = '1400px 0px'
const SCROLL_FALLBACK_PX = 1000
const MAX_FILL_PAGES = 20
const URL_SYNC_DEBOUNCE_MS = 400
const SCROLL_RESTORE_KEY_PREFIX = 'scroll_models_'
const MAX_TRANSIENT_RETRIES = 3
const RETRY_BASE_MS = 400
const BACK_TO_TOP_SHOW_PX = 800

/**
 * Real infinite scroll for the models grid via Turbo Streams.
 *
 * GET next page with Accept: text/vnd.turbo-stream.html
 * Server inserts cards before #models-scroll-sentinel and replaces the sentinel.
 *
 * Also: viewport fill, URL page sync, sessionStorage scroll restore on back,
 * transient error retry, end-of-list status, optional back-to-top control.
 */
export default class extends Controller {
  static targets = ['sentinel', 'status', 'backToTop', 'grid']
  static values = {
    nextUrl: { type: String, default: '' },
    startPage: { type: Number, default: 1 },
    perPage: { type: Number, default: 24 }
  }

  declare nextUrlValue: string
  declare startPageValue: number
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
  private urlSyncTimer: ReturnType<typeof setTimeout> | null = null
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
    if (this.urlSyncTimer != null) clearTimeout(this.urlSyncTimer)
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
        // Full HTML (e.g. login) — stop rather than loop
        this.exhausted = true
        this.nextUrlValue = ''
        this.updateStatus('')
        return false
      }

      this.lastLoadedUrl = url
      this.transientFailures = 0
      renderStreamMessage(html)

      // After streams: sentinel replaced — read next URL from new node
      this.syncNextUrlFromSentinel()
      // Target may have been recreated; re-bind IO
      this.setupObserver()

      if (!this.hasMore) {
        this.exhausted = true
        this.updateStatus(this.endMessage())
      } else {
        this.updateStatus('')
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

    if (this.urlSyncTimer != null) clearTimeout(this.urlSyncTimer)
    this.urlSyncTimer = setTimeout(() => {
      this.urlSyncTimer = null
      this.syncUrlQuietly()
    }, URL_SYNC_DEBOUNCE_MS)
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

  private syncUrlQuietly (): void {
    const cards = this.gridEl().querySelectorAll<HTMLElement>('.model-card')
    if (cards.length === 0) return
    const perPage = this.perPageValue > 0 ? this.perPageValue : 24
    const firstVisible = Array.from(cards).findIndex((c) => c.getBoundingClientRect().bottom > 80)
    const index = firstVisible >= 0 ? firstVisible : 0
    const page = Math.floor(index / perPage) + this.startPageValue

    const url = new URL(window.location.href)
    const current = parseInt(url.searchParams.get('page') ?? String(this.startPageValue), 10)
    if (page === current) return
    if (page <= 1) url.searchParams.delete('page')
    else url.searchParams.set('page', String(page))
    history.replaceState(history.state, '', url.toString())
  }

  private onBeforeVisit (): void {
    this.syncUrlQuietly()
    this.persistScrollY()
  }

  private storageKey (): string {
    const url = new URL(window.location.href)
    // Restore against path + filters, ignore page (handled separately)
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
