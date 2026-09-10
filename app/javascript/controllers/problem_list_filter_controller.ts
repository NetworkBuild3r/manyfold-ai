import { Controller } from '@hotwired/stimulus'

// Connects to data-controller="problem-list-filter"
export default class extends Controller {
  static targets = ['query', 'row', 'empty']

  declare readonly queryTarget: HTMLInputElement
  declare readonly rowTargets: HTMLElement[]
  declare readonly hasEmptyTarget: boolean
  declare readonly emptyTarget: HTMLElement

  filter (): void {
    const needle = this.queryTarget.value.trim().toLowerCase()
    let visible = 0
    this.rowTargets.forEach((row) => {
      const haystack = row.dataset.search ?? row.textContent ?? ''
      const show = needle === '' || haystack.includes(needle)
      row.classList.toggle('hidden', !show)
      if (show) visible += 1
    })
    if (this.hasEmptyTarget) {
      this.emptyTarget.classList.toggle('hidden', visible > 0)
    }
  }

  hideRow (event: Event): void {
    const row = (event.target as Element | null)?.closest?.('.problem-row')
    if (row instanceof HTMLElement) {
      row.classList.add('hidden')
    }
  }

  mergeSelected (event: Event): void {
    event.preventDefault()
    const checked = this.rowTargets.filter((el) => {
      const box = el.querySelector<HTMLInputElement>('input[type="checkbox"][name^="problems"]')
      return box?.checked === true
    })
    const mergeable = checked.find((el) => Boolean(el.dataset.mergeUrl))
    const url = mergeable?.dataset.mergeUrl
    if (url != null && url !== '') {
      const next = new URL(url, window.location.origin)
      if (!next.searchParams.has('return_to')) {
        next.searchParams.set('return_to', `${window.location.pathname}${window.location.search}`)
      }
      const href = `${next.pathname}${next.search}`
      const frame = document.querySelector<HTMLElement>('turbo-frame#duplicate-merge-dialog')
      if (frame != null) {
        frame.setAttribute('src', href)
        return
      }
      window.location.assign(href)
      return
    }
    if (checked.length > 0) {
      const form = this.element.querySelector<HTMLFormElement>('form')
      const resolve = form?.querySelector<HTMLInputElement>('input[type="submit"][name="resolve"]')
      if (form != null && resolve != null) {
        form.requestSubmit(resolve)
        return
      }
    }
    window.alert(this.element.getAttribute('data-problem-list-filter-merge-missing-value') ?? '')
  }
}
