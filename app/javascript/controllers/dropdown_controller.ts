import { Controller } from '@hotwired/stimulus'

// Replaces Bootstrap dropdown JS. Toggle menu on trigger click, close on outside click or Escape.
// Arrow key navigation: Up/Down move focus between menuitems, Home/End first/last, Enter activates.
// Connects to data-controller="dropdown". Requires data-dropdown-target="menu" on the menu element.
export default class extends Controller {
  static targets = ['menu']

  declare menuTarget: HTMLElement
  declare hasMenuTarget: boolean

  private readonly boundCloseOnClickOutside = (e: MouseEvent): void => { this.closeOnClickOutside(e) }
  private readonly boundCloseOnEscape = (e: KeyboardEvent): void => { this.closeOnEscape(e) }
  private readonly boundTriggerKeydown = (e: KeyboardEvent): void => { this.triggerKeydown(e) }
  private readonly boundMenuKeydown = (e: KeyboardEvent): void => { this.menuKeydown(e) }

  connect (): void {
    document.addEventListener('click', this.boundCloseOnClickOutside, true)
    document.addEventListener('keydown', this.boundCloseOnEscape)
    const trigger = this.element.querySelector<HTMLElement>('[aria-haspopup="menu"]')
    if (trigger) {
      trigger.addEventListener('keydown', this.boundTriggerKeydown)
    }
  }

  disconnect (): void {
    document.removeEventListener('click', this.boundCloseOnClickOutside, true)
    document.removeEventListener('keydown', this.boundCloseOnEscape)
    const trigger = this.element.querySelector<HTMLElement>('[aria-haspopup="menu"]')
    if (trigger) {
      trigger.removeEventListener('keydown', this.boundTriggerKeydown)
    }
    if (this.hasMenuTarget) {
      this.menuTarget.removeEventListener('keydown', this.boundMenuKeydown)
    }
  }

  toggle (event: Event): void {
    event.preventDefault()
    event.stopPropagation()
    if (this.hasMenuTarget) {
      const open = this.menuTarget.classList.toggle('show')
      this.syncAriaExpanded(open)
      if (open) {
        this.menuTarget.addEventListener('keydown', this.boundMenuKeydown)
        this.focusFirstMenuitem()
      } else {
        this.menuTarget.removeEventListener('keydown', this.boundMenuKeydown)
      }
    }
  }

  close (): void {
    if (this.hasMenuTarget) {
      this.menuTarget.classList.remove('show')
      this.menuTarget.removeEventListener('keydown', this.boundMenuKeydown)
      this.syncAriaExpanded(false)
      this.returnFocusToTrigger()
    }
  }

  private closeOnClickOutside (event: MouseEvent): void {
    if (!this.hasMenuTarget) return
    const target = event.target as Node
    if (this.element.contains(target)) return
    this.close()
  }

  private closeOnEscape (event: KeyboardEvent): void {
    if (event.key !== 'Escape') return
    this.close()
  }

  private triggerKeydown (event: KeyboardEvent): void {
    if (event.key !== 'ArrowDown' && event.key !== 'Enter' && event.key !== ' ') return
    if (!this.hasMenuTarget || !this.menuTarget.classList.contains('show')) {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        this.menuTarget.classList.add('show')
        this.syncAriaExpanded(true)
        this.menuTarget.addEventListener('keydown', this.boundMenuKeydown)
        this.focusFirstMenuitem()
      }
    }
  }

  private menuKeydown (event: KeyboardEvent): void {
    const items = this.getFocusableMenuitems()
    if (items.length === 0) return
    const current = document.activeElement as HTMLElement | null
    const currentIndex = current ? items.indexOf(current) : -1
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        if (currentIndex < items.length - 1) {
          items[currentIndex + 1].focus()
        } else {
          items[0].focus()
        }
        break
      case 'ArrowUp':
        event.preventDefault()
        if (currentIndex > 0) {
          items[currentIndex - 1].focus()
        } else {
          items[items.length - 1].focus()
        }
        break
      case 'Home':
        event.preventDefault()
        items[0].focus()
        break
      case 'End':
        event.preventDefault()
        items[items.length - 1].focus()
        break
      case 'Escape':
        event.preventDefault()
        this.close()
        break
    }
  }

  private getFocusableMenuitems (): HTMLElement[] {
    const list = this.menuTarget.querySelectorAll('[role="menuitem"]')
    return Array.from(list).filter((el): el is HTMLElement => {
      const html = el as HTMLElement
      return html.tabIndex !== -1 && !html.hasAttribute('aria-disabled')
    })
  }

  private focusFirstMenuitem (): void {
    const items = this.getFocusableMenuitems()
    if (items.length > 0) {
      items[0].focus()
    }
  }

  private returnFocusToTrigger (): void {
    const trigger = this.element.querySelector<HTMLElement>('[aria-haspopup="menu"]')
    if (trigger) {
      trigger.focus()
    }
  }

  private syncAriaExpanded (open: boolean): void {
    const trigger = this.element.querySelector('[aria-haspopup][aria-expanded]')
    if (trigger !== null) {
      trigger.setAttribute('aria-expanded', String(open))
    }
  }
}
