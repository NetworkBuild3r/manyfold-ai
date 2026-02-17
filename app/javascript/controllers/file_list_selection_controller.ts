import BaseSelectionController from './base_selection_controller'

const STORAGE_KEY_PREFIX = 'file_list_selection_'

// Connects to data-controller="file-list-selection". Manages selection state for file
// cards (bubbles) and toolbar (Bulk edit, Split out, Clear). Selection is per-model
// in sessionStorage.
export default class extends BaseSelectionController {
  static targets = [
    'bubble',
    'toolbar',
    'bulkEditForm',
    'bulkEditIdsContainer',
    'splitForm',
    'splitIdsContainer',
    'clearButton'
  ]

  static values = { modelId: { type: String, default: '' } }

  declare bulkEditFormTarget: HTMLFormElement
  declare hasBulkEditFormTarget: boolean
  declare bulkEditIdsContainerTarget: HTMLElement
  declare hasBulkEditIdsContainerTarget: boolean
  declare splitFormTarget: HTMLFormElement
  declare hasSplitFormTarget: boolean
  declare splitIdsContainerTarget: HTMLElement
  declare hasSplitIdsContainerTarget: boolean
  declare clearButtonTarget: HTMLElement
  declare modelIdValue: string

  get storageKey (): string {
    return STORAGE_KEY_PREFIX + (this.modelIdValue || 'default')
  }

  get idDataAttribute (): string {
    return 'fileId'
  }

  get selectedClass (): string {
    return 'file-list-selection-selected'
  }

  syncToolbar (): void {
    if (!this.hasToolbarTarget) return
    const count = this.selectedIds.size
    const hasSelectedOnPage = this.hasSelectedOnPage
    this.toolbarTarget.hidden = count === 0 || !hasSelectedOnPage

    if (count > 0 && hasSelectedOnPage) {
      this.populateFormIds()
    } else if (count === 0) {
      this.clearFormIds()
    }
  }

  /** Populate hidden ids in bulk edit and split forms before submit */
  populateFormIds (): void {
    if (this.hasBulkEditIdsContainerTarget) {
      this.bulkEditIdsContainerTarget.innerHTML = ''
      this.selectedIds.forEach((id) => {
        const input = document.createElement('input')
        input.type = 'hidden'
        input.name = 'ids[]'
        input.value = id
        this.bulkEditIdsContainerTarget.appendChild(input)
      })
    }

    if (this.hasSplitIdsContainerTarget) {
      this.splitIdsContainerTarget.innerHTML = ''
      this.selectedIds.forEach((id) => {
        const input = document.createElement('input')
        input.type = 'hidden'
        input.name = 'ids[]'
        input.value = id
        this.splitIdsContainerTarget.appendChild(input)
      })
    }
  }

  /** Clear hidden ids when selection is empty */
  clearFormIds (): void {
    if (this.hasBulkEditIdsContainerTarget) {
      this.bulkEditIdsContainerTarget.innerHTML = ''
    }
    if (this.hasSplitIdsContainerTarget) {
      this.splitIdsContainerTarget.innerHTML = ''
    }
  }

  /** Call before split/bulk edit submit to ensure ids are populated */
  prepareSubmit (): void {
    this.populateFormIds()
  }

  clearOnSubmit (): void {
    this.prepareSubmit()
    this.clear()
  }
}
