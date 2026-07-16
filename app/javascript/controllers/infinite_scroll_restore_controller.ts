import { Controller } from '@hotwired/stimulus'

const STORAGE_KEY_PREFIX = 'scroll_models_'
const FILL_BUFFER_PX = 500
const PREFETCH_ROOT_MARGIN = '1000px 0px'
const MAX_FILL_PAGES = 25
const URL_SYNC_DEBOUNCE_MS = 400

/**
 * Continuous card stream for the model grid.
 *
 * - Fetches flat HTML fragments (X-Infinite-Scroll) and appends .model-card nodes
 * - Fills the viewport on connect (no empty half-page / "page 5 with 12 cards")
 * - Prefetches ~1000px before the bottom sentinel
 * - Does NOT nest turbo-frames; no full-width loading row between chunks
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
  declare hasNextUrlValue: boolean
  declare sentinelTarget: HTMLElement
  declare hasSentinelTarget: boolean

  private loading = false
  private exhausted = false
  private observer: IntersectionObserver | null = null
  private boundOnBeforeVisit: (e: Event) => void
  private boundOnScroll: () => void
  private urlSyncTimer: ReturnType<typeof setTimeout> | null = null
  private pagesLoaded = 1

  connect (): void {
    this.boundOnBeforeVisit = this.onBeforeVisit.bind(this)
    this.boundOnScroll = this.onScroll.bind(this)
    document.addEventListener('turbo:before-visit', this.boundOnBeforeVisit)
    window.addEventListener('scroll', this.boundOnScroll, { passive: true })

    if (this.hasSentinelTarget) {
      this.observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            void this.loadMore()
          }
        },
        { root: null, rootMargin: PREFETCH_ROOT_MARGIN, threshold: 0 }
      )
      this.observer.observe(this.sentinelTarget)
      this.updateSentinelVisibility()
    }

    // Fill the screen immediately so browse never looks like thin pagination
    void this.fillViewport()
  }

  disconnect (): void {
    document.removeEventListener('turbo:before-visit', this.boundOnBeforeVisit)
    window.removeEventListener('scroll', this.boundOnScroll)
    this.observer?.disconnect()
    this.observer = null
    if (this.urlSyncTimer != null) clearTimeout(this.urlSyncTimer)
  }

  private get hasMore (): boolean {
    return !this.exhausted && typeof this.nextUrlValue === 'string' && this.nextUrlValue.length > 0
  }

  private updateSentinelVisibility (): void {
    if (!this.hasSentinelTarget) return
    if (this.hasMore) {
      this.sentinelTarget.hidden = false
      this.sentinelTarget.removeAttribute('hidden')
    } else {
      this.sentinelTarget.hidden = true
      this.sentinelTarget.setAttribute('hidden', 'hidden')
    }
  }

  /** Keep loading until the grid extends past the viewport (or no more pages). */
  private async fillViewport (): Promise<void> {
    let guard = 0
    while (guard < MAX_FILL_PAGES && this.hasMore && !this.viewportSatisfied()) {
      guard += 1
      const loaded = await this.loadMore()
      if (!loaded) break
    }
  }

  private viewportSatisfied (): boolean {
    const bottom = this.element.getBoundingClientRect().bottom
    return bottom > window.innerHeight + FILL_BUFFER_PX
  }

  /**
   * @returns true if a page was appended
   */
  private async loadMore (): Promise<boolean> {
    if (this.loading || !this.hasMore) return false
    this.loading = true
    this.element.classList.add('is-loading-more')

    const url = this.nextUrlValue
    try {
      const response = await fetch(url, {
        headers: {
          Accept: 'text/html',
          'X-Infinite-Scroll': '1'
        },
        credentials: 'same-origin'
      })
      if (!response.ok) {
        console.warn('[infinite-scroll] page load failed', response.status, url)
        this.exhausted = true
        this.nextUrlValue = ''
        this.updateSentinelVisibility()
        return false
      }

      const html = await response.text()
      const doc = new DOMParser().parseFromString(html, 'text/html')
      const page = doc.querySelector('.model-stream-page')
      if (page == null) {
        const cards = doc.querySelectorAll('.model-card')
        if (cards.length === 0) {
          this.exhausted = true
          this.nextUrlValue = ''
          this.updateSentinelVisibility()
          return false
        }
        this.appendCards(cards)
        this.pagesLoaded += 1
        this.exhausted = true
        this.nextUrlValue = ''
        this.updateSentinelVisibility()
        return true
      }

      const cards = page.querySelectorAll('.model-card')
      this.appendCards(cards)
      this.pagesLoaded += 1

      const next = page.getAttribute('data-next-url') ?? ''
      if (next.length > 0) {
        this.nextUrlValue = next
      } else {
        this.nextUrlValue = ''
        this.exhausted = true
      }
      this.updateSentinelVisibility()
      return cards.length > 0
    } catch (e) {
      console.warn('[infinite-scroll] load error', e)
      return false
    } finally {
      this.loading = false
      this.element.classList.remove('is-loading-more')
    }
  }

  private appendCards (cards: NodeListOf<Element> | Element[]): void {
    const list = Array.from(cards)
    const sentinel = this.hasSentinelTarget ? this.sentinelTarget : null
    for (const card of list) {
      const node = document.importNode(card, true)
      if (sentinel != null && sentinel.parentNode === this.element) {
        this.element.insertBefore(node, sentinel)
      } else {
        this.element.appendChild(node)
      }
    }
  }

  private onScroll (): void {
    if (this.urlSyncTimer != null) clearTimeout(this.urlSyncTimer)
    this.urlSyncTimer = setTimeout(() => {
      this.urlSyncTimer = null
      this.syncUrlQuietly()
    }, URL_SYNC_DEBOUNCE_MS)
  }

  private syncUrlQuietly (): void {
    const cardNodes = this.element.querySelectorAll<HTMLElement>('.model-card')
    if (cardNodes.length === 0) return
    const perPage = this.perPageValue > 0 ? this.perPageValue : 24
    const firstVisible = Array.from(cardNodes)
      .findIndex((c) => c.getBoundingClientRect().bottom > 80)
    const index = firstVisible >= 0 ? firstVisible : 0
    const page = Math.floor(index / perPage) + this.startPageValue

    const url = new URL(window.location.href)
    const current = parseInt(url.searchParams.get('page') ?? String(this.startPageValue), 10)
    if (page === current) return
    if (page <= 1) {
      url.searchParams.delete('page')
    } else {
      url.searchParams.set('page', String(page))
    }
    history.replaceState(history.state, '', url.toString())
  }

  private onBeforeVisit (): void {
    this.syncUrlQuietly()
    try {
      const key = this.storageKey()
      sessionStorage.setItem(key, String(window.scrollY))
    } catch {
      // ignore
    }
  }

  private storageKey (): string {
    const url = new URL(window.location.href)
    url.searchParams.delete('page')
    const q = url.searchParams.toString()
    return STORAGE_KEY_PREFIX + url.pathname + (q.length > 0 ? `?${q}` : '')
  }
}
