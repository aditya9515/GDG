import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const semanticColorUtilities =
  /\b(?:text|bg|border|ring)-(?:red|orange|amber|yellow|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-/g
const unsafeBlackWhiteUtilities =
  /\b(?:hover:bg-white[^\n"'`]*hover:text-black|hover:text-black[^\n"'`]*hover:bg-white|(?:border-white\s+)?bg-white\s+text-black|text-black[^\n"'`]*bg-white)\b/g

function collectTsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = join(dir, entry)
    const stats = statSync(fullPath)
    if (stats.isDirectory()) {
      return collectTsxFiles(fullPath)
    }
    return fullPath.endsWith('.tsx') ? [fullPath] : []
  })
}

describe('monochrome UI contract', () => {
  it('keeps user-facing app and component files free of semantic color utility classes', () => {
    const files = [...collectTsxFiles(join(process.cwd(), 'src/app')), ...collectTsxFiles(join(process.cwd(), 'src/components'))]
    const offenders = files.flatMap((file) => {
      const source = readFileSync(file, 'utf8')
      const matches = source.match(semanticColorUtilities) ?? []
      return matches.map((match) => `${file.replace(process.cwd(), '')}: ${match}`)
    })

    expect(offenders).toEqual([])
  })

  it('keeps user-facing hover and active states free of unsafe black-on-black combinations', () => {
    const files = [...collectTsxFiles(join(process.cwd(), 'src/app')), ...collectTsxFiles(join(process.cwd(), 'src/components'))]
    const offenders = files.flatMap((file) => {
      const source = readFileSync(file, 'utf8')
      const matches = source.match(unsafeBlackWhiteUtilities) ?? []
      return matches.map((match) => `${file.replace(process.cwd(), '')}: ${match}`)
    })

    expect(offenders).toEqual([])
  })

  it('does not treat translucent white hover classes as solid primary hovers', () => {
    const source = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf8')

    expect(source).not.toContain('[class*="hover:bg-white"]')
    expect(source).toContain('[class~="hover:bg-white"]')
  })
})
