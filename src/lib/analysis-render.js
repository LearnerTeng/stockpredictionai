function clearNode(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild)
  }
}

export function renderAnalysisSections(container, sections = []) {
  clearNode(container)

  sections.forEach((section) => {
    const card = document.createElement('article')
    card.className = 'analysis-section-card'

    const heading = document.createElement('h3')
    heading.textContent = section.heading
    card.appendChild(heading)

    const list = document.createElement('ul')
    list.className = 'analysis-bullet-list'

    section.bullets.forEach((bullet) => {
      const item = document.createElement('li')
      item.textContent = bullet
      list.appendChild(item)
    })

    card.appendChild(list)
    container.appendChild(card)
  })
}
