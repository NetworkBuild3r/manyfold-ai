import { Controller } from '@hotwired/stimulus'

// Wraps the native <dialog> element. open/showModal and close with backdrop click and focus restore.
// Focus trap: focus first focusable on open, trap Tab inside dialog, Escape closes.
// Connects to data-controller="dialog". Trigger uses data-action="click->dialog#open"; close button uses click->dialog#close.
export default class extends Controller {
  static targets = ['dialog']

  declare dialogTarget: HTMLDialogElement
  declare hasDialogTarget: boolean

  private lastFocused: HTMLElement | null = null
  private readonly boundBackdropClick = (e: MouseEvent): void => this.onBackdropClick(e)
  private readonly boundKeydown = (e: KeyboardEvent): void => this.trapKeydown(e)

  open (event: Event): void {
    event.preventDefault()
    if (!this.hasDialogTarget) return
    this.lastFocused = (event.currentTarget as HTMLElement) ?? document.activeElement as HTMLElement | null
    this.dialogTarget.showModal()
    this.dialogTarget.addEventListener('click', this.boundBackdropClick)
    this.dialogTarget.addEventListener('keydown', this.boundKeydown)
    this.focusFirstFocusable()
  }

  close (event?: Event): void {
    if (event != null) event.preventDefault()
    if (!this.hasDialogTarget) return
    this.dialogTarget.removeEventListener('click', this.boundBackdropClick)
    this.dialogTarget.removeEventListener('keydown', this.boundKeydown)
    this.dialogTarget.close()
    if (this.lastFocused != null) {
      this.lastFocused.focus()
      this.lastFocused = null
    }
  }

  private focusFirstFocusable (): void {
    const focusable = this.getFocusables()
    if (focusable.length > 0) {
      focusable[0].focus()
    }
  }

  private getFocusables (): HTMLElement[] {
    const sel = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    return Array.from(this.dialogTarget.querySelectorAll<HTMLElement>(sel))
  }

  private trapKeydown (event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      this.close(event)
      return
    }
    if (event.key !== 'Tab') return
    const focusables = this.getFocusables()
    if (focusables.length === 0) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (event.shiftKey) {
      if (document.activeElement === first) {
        event.preventDefault()
        last.focus()
      }
    } else {
      if (document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
  }

  private onBackdropClick (event: MouseEvent): void {
    if (event.target === this.dialogTarget) {
      this.close()
    }
  }
}
