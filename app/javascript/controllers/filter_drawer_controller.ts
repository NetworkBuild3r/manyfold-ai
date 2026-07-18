import { Controller } from '@hotwired/stimulus'

/**
 * Mobile filter drawer for library browse.
 * Desktop (lg+): panel is a normal sticky sidebar — open/close are no-ops.
 * Mobile: panel slides in from the left over a backdrop.
 */
export default class extends Controller {
  static targets = ['panel', 'backdrop']

  declare panelTarget: HTMLElement
  declare hasPanelTarget: boolean
  declare backdropTarget: HTMLElement
  declare hasBackdropTarget: boolean

  private readonly boundKeydown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') this.close()
  }

  open (event?: Event): void {
    event?.preventDefault()
    if (!this.hasPanelTarget || this.isDesktop()) return
    this.panelTarget.classList.add('is-open')
    this.panelTarget.setAttribute('aria-hidden', 'false')
    if (this.hasBackdropTarget) {
      this.backdropTarget.removeAttribute('hidden')
    }
    document.body.classList.add('overflow-hidden')
    document.addEventListener('keydown', this.boundKeydown)
    const closeBtn = this.panelTarget.querySelector<HTMLElement>('[data-filter-drawer-close]')
    closeBtn?.focus()
    this.syncTriggerExpanded(true)
  }

  close (event?: Event): void {
    event?.preventDefault()
    if (!this.hasPanelTarget) return
    this.panelTarget.classList.remove('is-open')
    this.panelTarget.setAttribute('aria-hidden', 'true')
    if (this.hasBackdropTarget) {
      this.backdropTarget.setAttribute('hidden', 'hidden')
    }
    document.body.classList.remove('overflow-hidden')
    document.removeEventListener('keydown', this.boundKeydown)
    this.syncTriggerExpanded(false)
  }

  connect (): void {
    if (this.isDesktop() && this.hasPanelTarget) {
      this.panelTarget.setAttribute('aria-hidden', 'false')
    }
  }

  private syncTriggerExpanded (open: boolean): void {
    this.element.querySelectorAll<HTMLElement>('[data-action*="filter-drawer#open"]').forEach((btn) => {
      btn.setAttribute('aria-expanded', open ? 'true' : 'false')
    })
  }

  disconnect (): void {
    document.removeEventListener('keydown', this.boundKeydown)
    document.body.classList.remove('overflow-hidden')
  }

  private isDesktop (): boolean {
    return window.matchMedia('(min-width: 1024px)').matches
  }
}
