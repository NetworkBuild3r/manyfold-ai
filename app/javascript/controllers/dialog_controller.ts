import { Controller } from '@hotwired/stimulus'

// Wraps native <dialog>. Supports one or many dialogs under the same controller:
// - data-dialog-target="dialog" (legacy single), or
// - trigger data-dialog-id="<dialog element id>" (INIT-017 multi-modal on edit)
export default class extends Controller {
  static targets = ['dialog']

  declare dialogTarget: HTMLDialogElement
  declare hasDialogTarget: boolean

  private lastFocused: HTMLElement | null = null
  private activeDialog: HTMLDialogElement | null = null
  private readonly boundBackdropClick = (e: MouseEvent): void => this.onBackdropClick(e)
  private readonly boundKeydown = (e: KeyboardEvent): void => this.trapKeydown(e)

  open (event: Event): void {
    event.preventDefault()
    const trigger = event.currentTarget as HTMLElement
    this.lastFocused = trigger ?? document.activeElement as HTMLElement | null
    const byId = trigger?.dataset?.dialogId
    const dialog = (byId != null ? document.getElementById(byId) : null) as HTMLDialogElement | null
      ?? (this.hasDialogTarget ? this.dialogTarget : null)
    if (dialog == null) return
    this.activeDialog = dialog
    dialog.showModal()
    dialog.addEventListener('click', this.boundBackdropClick)
    dialog.addEventListener('keydown', this.boundKeydown)
    this.focusFirstFocusable()
  }

  close (event?: Event): void {
    if (event != null) event.preventDefault()
    const dialog = this.activeDialog ?? (this.hasDialogTarget ? this.dialogTarget : null)
    if (dialog == null) return
    dialog.removeEventListener('click', this.boundBackdropClick)
    dialog.removeEventListener('keydown', this.boundKeydown)
    dialog.close()
    this.activeDialog = null
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
    const dialog = this.activeDialog ?? (this.hasDialogTarget ? this.dialogTarget : null)
    if (dialog == null) return []
    const sel = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    return Array.from(dialog.querySelectorAll<HTMLElement>(sel)).filter((el) => !el.hasAttribute('disabled'))
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
    if (event.target === this.activeDialog) {
      this.close()
    }
  }
}
