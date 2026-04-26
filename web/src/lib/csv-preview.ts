export interface CsvPreview {
  headers: string[]
  rows: Record<string, string>[]
  rowCount: number
  warnings: string[]
}

function parseLine(line: string): string[] {
  const cells: string[] = []
  let current = ''
  let quoted = false

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    const next = line[index + 1]
    if (char === '"' && quoted && next === '"') {
      current += '"'
      index += 1
      continue
    }
    if (char === '"') {
      quoted = !quoted
      continue
    }
    if (char === ',' && !quoted) {
      cells.push(current.trim())
      current = ''
      continue
    }
    current += char
  }

  cells.push(current.trim())
  return cells
}

export function parseCsvPreview(text: string, limit = 8): CsvPreview {
  const warnings: string[] = []
  const lines = text
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0)

  if (lines.length === 0) {
    return { headers: [], rows: [], rowCount: 0, warnings: ['CSV is empty.'] }
  }

  const headers = parseLine(lines[0]).map((header, index) => header || `column_${index + 1}`)
  const rows = lines.slice(1).map((line, rowIndex) => {
    const cells = parseLine(line)
    if (cells.length !== headers.length) {
      warnings.push(`Row ${rowIndex + 2} has ${cells.length} cells but header has ${headers.length}.`)
    }
    return Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? '']))
  })

  return {
    headers,
    rows: rows.slice(0, limit),
    rowCount: rows.length,
    warnings: [...new Set(warnings)].slice(0, 5),
  }
}

export function csvTextToFile(text: string, filename: string): File {
  return new File([text], filename, { type: 'text/csv' })
}
