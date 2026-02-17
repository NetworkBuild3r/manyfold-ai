import BaseSelectionController from './base_selection_controller'

const STORAGE_KEY = 'model_list_selection'

// Connects to data-controller="model-list-selection". Manages selection state for model
// cards (bubbles) and toolbar (Edit single, Bulk edit, Clear). Selection is optional
// persisted to sessionStorage so refresh keeps it; clear on bulk-edit entry or when clearing.
export default class extends BaseSelectionController {
  static targets = ['bubble', 'toolbar', 'editLink', 'bulkEditForm', 'idsContainer', 'clearButton', 'mergeLink']

  declare editLinkTarget: HTMLAnchorElement
  declare hasEditLinkTarget: boolean
  declare idsContainerTarget: HTMLElement
  declare hasIdsContainerTarget: boolean
  declare mergeLinkTarget: HTMLAnchorElement
  declare hasMergeLinkTarget: boolean

  get storageKey (): string {
    return STORAGE_KEY
  }

  get idDataAttribute (): string {
    return 'modelId'
  }

  get selectedClass (): string {
    return 'model-card-selection-selected'
  }

  syncToolbar (): void {
    if (!this.hasToolbarTarget) return
    const count = this.selectedIds.size
    const hasSelectedOnPage = this.hasSelectedOnPage
    this.toolbarTarget.hidden = count === 0 || !hasSelectedOnPage

    if (count > 0 && hasSelectedOnPage) {
      if (this.hasEditLinkTarget) {
        if (count === 1) {
          const id = [...this.selectedIds][0]
          this.editLinkTarget.href = (this.editLinkTarget.dataset.baseHref ?? '').replace('__ID__', id)
          this.editLinkTarget.hidden = false
        } else {
          this.editLinkTarget.hidden = true
        }
      }

      if (this.hasIdsContainerTarget) {
        this.idsContainerTarget.innerHTML = ''
        this.selectedIds.forEach((id) => {
          const input = document.createElement('input')
          input.type = 'hidden'
          input.name = 'ids[]'
          input.value = id
          this.idsContainerTarget.appendChild(input)
        })
      }

      if (this.hasMergeLinkTarget) {
        if (count >= 2) {
          const base = this.mergeLinkTarget.dataset.baseHref ?? ''
          const query = [...this.selectedIds].map((id) => 'models[]=' + encodeURIComponent(id)).join('&')
          this.mergeLinkTarget.href = query ? base + '?' + query : base
          this.mergeLinkTarget.hidden = false
        } else {
          this.mergeLinkTarget.hidden = true
        }
      }
    } else if (this.hasMergeLinkTarget) {
      this.mergeLinkTarget.hidden = true
    }
  }
}
