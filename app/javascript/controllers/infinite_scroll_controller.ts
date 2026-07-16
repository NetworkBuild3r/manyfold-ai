import { Controller } from '@hotwired/stimulus'
import { renderStreamMessage } from '@hotwired/turbo'

const FILL_BUFFER_PX = 600
const PREFETCH_ROOT_MARGIN = '1200px 0px'
const SCROLL_FALLBACK_PX = 900
const MAX_FILL_PAGES = 20
const URL_SYNC_DEBOUNCE_MS = 400

/**
 * Real infinite scroll for the models grid via Turbo Streams.
 *
 * GET next page with Accept: text/vnd.turbo-stream.html
 * Server inserts cards before #models-scroll-sentinel and replaces the sentinel.
 */
export default class extends Controller {
  static targets = ['sentinel']
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

  private loading = false
  private exhausted = false
  private observer: IntersectionObserver | null = null
  private boundOnScroll: () => void
  private boundOnBeforeVisit: () => void
  private scrollTicking = false
  private urlSyncTimer: ReturnType<typeof setTimeout> | null = null

  connect (): void {
    this.boundOnScroll = this.onScroll.bind(this)
    this.boundOnBeforeVisit = this.onBeforeVisit.bind(this)
    window.addEventListener('scroll', this.boundOnScroll, { passive: true })
    document.addEventListener('turbo:before-visit', this.boundOnBeforeVisit)

    this.syncNextUrlFromSentinel()
    this.setupObserver()
    void this.fillViewport()
  }

  disconnect (): void {
    window.removeEventListener('scroll', this.boundOnScroll)
    document.removeEventListener('turbo:before-visit', this.boundOnBeforeVisit)
    this.observer?.disconnect()
    this.observer = null
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
    } else {
      this.nextUrlValue = ''
      this.exhausted = true
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

  private viewportSatisfied (): boolean {
    const bottom = this.element.getBoundingClientRect().bottom
    return bottom > window.innerHeight + FILL_BUFFER_PX
  }

  private nearBottom (): boolean {
    const scrollBottom = window.scrollY + window.innerHeight
    const docHeight = document.documentElement.scrollHeight
    return docHeight - scrollBottom < SCROLL_FALLBACK_PX
  }

  private async loadMore (): Promise<boolean> {
    if (this.loading || !this.hasMore) return false
    this.loading = true
    this.element.classList.add('is-loading-more')

    const url = this.nextUrlValue
    try {
      const response = await fetch(url, {
        headers: {
          Accept: 'text/vnd.turbo-stream.html, text/html',
          'X-Infinite-Scroll': '1'
        },
        credentials: 'same-origin'
      })

      if (!response.ok) {
        console.warn('[infinite-scroll] HTTP', response.status, url)
        // Do not permanently exhaust on 5xx; allow retry on next scroll
        if (response.status === 401 || response.status === 403 || response.status === 404) {
          this.exhausted = true
          this.nextUrlValue = ''
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
        return false
      }

      renderStreamMessage(html)

      // After streams: sentinel replaced — read next URL from new node
      this.syncNextUrlFromSentinel()
      // Target may have been recreated; re-bind IO
      this.setupObserver()

      if (!this.hasMore) {
        this.exhausted = true
      }

      return true
    } catch (e) {
      console.warn('[infinite-scroll] load error', e)
      return false
    } finally {
      this.loading = false
      this.element.classList.remove('is-loading-more')
    }
  }

  private onScroll (): void {
    if (!this.scrollTicking) {
      this.scrollTicking = true
      requestAnimationFrame(() => {
        this.scrollTicking = false
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

  private syncUrlQuietly (): void {
    const cards = this.element.querySelectorAll<HTMLElement>('.model-card')
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
  }
}
