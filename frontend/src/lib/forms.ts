/** Move focus to the first of `names` that is a field of `form` (for a radio group, its first
 * option), so keyboard and screen-reader users land on what needs fixing. */
export function focusFirstField(form: HTMLFormElement, names: readonly string[]): void {
  for (const name of names) {
    const item = form.elements.namedItem(name)
    const target = item instanceof RadioNodeList ? item[0] : item
    if (target instanceof HTMLElement) {
      target.focus()
      return
    }
  }
}
