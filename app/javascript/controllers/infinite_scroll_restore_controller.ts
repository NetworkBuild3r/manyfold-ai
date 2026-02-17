import { Controller } from '@hotwired/stimulus'

const STORAGE_KEY_PREFIX = 'scroll_models_'
const RESTORE_MAX_ATTEMPTS = 30
const RESTORE_RETRY_MS = 100
const PAGE_THRESHOLD_PX = 120
const SCROLL_AT_TOP_THRESHOLD_PX = 50

// Syncs URL ?page=N on scroll, saves scroll before navigation, restores scroll on back.
// Turbo cache is primary; sessionStorage fallback when cache misses.
export default class extends Controller {
  static values = {
    perPage: Number
  }

  declare perPageValue: number
  declare hasPerPageValue: boolean

  private boundOnFrameLoad: (e: Event) => void
  private boundOnBeforeVisit: (e: Event) => void
  private boundOnScroll: () => void
  private scrollTicking = false
  private restoreComplete = false
  private restoreAttempts = 0
  private restoreTimer: ReturnType<typeof setTimeout> | null = null

  connect (): void {
    if (typeof history !== 'undefined') {
      history.scrollRestoration = 'manual'
    }
    this.boundOnFrameLoad = this.onFrameLoad.bind(this)
    this.boundOnBeforeVisit = this.onBeforeVisit.bind(this)
    this.boundOnScroll = this.onScroll.bind(this)

    this.element.addEventListener('turbo:frame-load', this.boundOnFrameLoad)
    document.addEventListener('turbo:before-visit', this.boundOnBeforeVisit)
    window.addEventListener('scroll', this.boundOnScroll, { passive: true })

    requestAnimationFrame(() => {
      this.maybeRestoreScroll()
    })
  }

  disconnect (): void {
    this.element.removeEventListener('turbo:frame-load', this.boundOnFrameLoad)
    document.removeEventListener('turbo:before-visit', this.boundOnBeforeVisit)
    window.removeEventListener('scroll', this.boundOnScroll)
    this.cancelPendingRestore()
  }

  private onFrameLoad (event: Event): void {
    const target = (event as CustomEvent).target
    if (!(target instanceof HTMLElement)) return
    if (!this.element.contains(target)) return
    this.syncUrlToViewport()
  }

  private onScroll (): void {
    if (this.scrollTicking) return
    this.scrollTicking = true
    requestAnimationFrame(() => {
      this.scrollTicking = false
      this.syncUrlToViewport()
    })
  }

  private syncUrlToViewport (): void {
    const visiblePage = this.detectVisiblePage()
    if (visiblePage == null) return
    const url = new URL(window.location.href)
    const currentPage = parseInt(url.searchParams.get('page') ?? '1', 10)
    if (currentPage === visiblePage) return

    if (visiblePage <= 1) {
      url.searchParams.delete('page')
    } else {
      url.searchParams.set('page', String(visiblePage))
    }
    history.replaceState(history.state, '', url.toString())
  }

  private detectVisiblePage (): number | null {
    const cards = Array.from(this.element.querySelectorAll<HTMLElement>('.model-card'))
    if (cards.length === 0) return null

    const firstVisibleIndex = cards.findIndex((card) => card.getBoundingClientRect().bottom > PAGE_THRESHOLD_PX)
    const cardIndex = firstVisibleIndex >= 0 ? firstVisibleIndex : cards.length - 1
    const perPage = this.hasPerPageValue && this.perPageValue > 0 ? this.perPageValue : 12

    return Math.floor(cardIndex / perPage) + 1
  }

  private onBeforeVisit (): void {
    this.syncUrlToViewport()
    this.saveScroll()
  }

  private saveScroll (): void {
    try {
      const key = this.storageKey()
      sessionStorage.setItem(key, String(window.scrollY))
    } catch (e) {
      console.warn('[infinite-scroll-restore] Could not save scroll:', e)
    }
  }

  private storageKey (): string {
    const url = new URL(window.location.href)
    url.searchParams.delete('page')
    const normalizedSearch = url.searchParams.toString()
    return STORAGE_KEY_PREFIX + url.pathname + (normalizedSearch.length > 0 ? `?${normalizedSearch}` : '')
  }

  private detectRestorationNeeded (): boolean {
    const page = new URL(window.location.href).searchParams.get('page')
    const isDeepPage = page !== null && parseInt(page, 10) > 1
    const scrollIsAtTop = window.scrollY < SCROLL_AT_TOP_THRESHOLD_PX
    return isDeepPage && scrollIsAtTop
  }

  private maybeRestoreScroll (): void {
    if (this.restoreComplete) return

    const url = new URL(window.location.href)
    if (!url.searchParams.has('page')) {
      this.restoreComplete = true
      return
    }

    if (!this.detectRestorationNeeded()) {
      this.restoreComplete = true
      return
    }

    this.runFallbackRestore()
  }

  private runFallbackRestore (): void {
    try {
      const key = this.storageKey()
      const saved = sessionStorage.getItem(key)
      if (saved === null) {
        this.restoreComplete = true
        return
      }
      const scrollY = parseInt(saved, 10)
      if (Number.isNaN(scrollY) || scrollY < 0) {
        this.restoreComplete = true
        return
      }

      const maxScroll = document.documentElement.scrollHeight - window.innerHeight
      if (scrollY > maxScroll) {
        if (this.restoreAttempts < RESTORE_MAX_ATTEMPTS) {
          this.restoreAttempts += 1
          this.restoreTimer = setTimeout(() => {
            this.restoreTimer = null
            this.runFallbackRestore()
          }, RESTORE_RETRY_MS)
        } else {
          this.restoreComplete = true
        }
        return
      }

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.scrollTo(0, scrollY)
          try {
            sessionStorage.removeItem(this.storageKey())
          } catch {
            // ignore
          }
          this.restoreComplete = true
        })
      })
    } catch (e) {
      console.warn('[infinite-scroll-restore] Could not restore scroll:', e)
      this.restoreComplete = true
    }
  }

  private cancelPendingRestore (): void {
    if (this.restoreTimer != null) {
      clearTimeout(this.restoreTimer)
      this.restoreTimer = null
    }
  }
}
