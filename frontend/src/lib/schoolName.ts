/** Display-only school name shortening -- never mutates the stored name.
 * Drops the redundant trailing "w/we <city>" clause (verified against the
 * school's own city field, since it's shown separately anyway) and
 * abbreviates the long, near-universal type prefixes. Everything else is
 * left as-is rather than risk mangling a patron's name. */

const STRICT_ROMAN_RE = /^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/i
const LOWERCASE_WORDS = new Set(["im.", "im", "nr", "w", "we", "z", "ze", "i", "dla", "im.,"])

function stripDiacritics(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
}

function isRomanNumeral(word: string): boolean {
  const bare = word.replace(/[."]/g, "")
  return bare.length > 0 && STRICT_ROMAN_RE.test(bare)
}

/** A lone "I" is genuinely ambiguous (Polish "i" = "and" vs. numeral "1st"),
 * but only at name-start does the numeral reading apply -- elsewhere it's
 * almost always the conjunction. Every other roman numeral (II, III, IV,
 * V, IX...) isn't a real Polish word, so it's safe to preserve anywhere,
 * which matters for patron names like "Jana Pawła II". */
function isNumeralHere(word: string, index: number): boolean {
  const bare = word.replace(/[."]/g, "")
  if (!isRomanNumeral(word)) return false
  return !(bare.toUpperCase() === "I" && index >= 2)
}

function capitalizeFirstLetter(word: string): string {
  const idx = word.search(/\p{L}/u)
  if (idx === -1) return word
  return word.slice(0, idx) + word.charAt(idx).toUpperCase() + word.slice(idx + 1)
}

function toDisplayCase(text: string): string {
  return text
    .split(" ")
    .map((word, i) => {
      if (word === "") return word
      if (isNumeralHere(word, i)) return word.toUpperCase()
      const lower = word.toLowerCase()
      if (LOWERCASE_WORDS.has(lower)) return lower
      return capitalizeFirstLetter(lower)
    })
    .join(" ")
}

/** Strips a trailing " w <city>" / " we <city>" clause, but only when the
 * trailing word's diacritic-stripped stem actually matches the school's own
 * verified city -- never a blind regex strip, since some names end in a
 * real word that happens to follow " w ". */
function stripTrailingCityClause(name: string, city: string | null): string {
  if (!city) return name
  const match = name.match(/^(.*)\s+WE?\s+([\p{L}][\p{L}\-]*(?:\s+[\p{L}\-]+)*)$/iu)
  if (!match) return name
  const [, before, trailing] = match

  const trailingFirstWord = stripDiacritics(trailing.split(/\s+/)[0])
  const cityFirstWord = stripDiacritics(city.split(/\s+/)[0])
  const threshold = Math.min(4, cityFirstWord.length)
  if (threshold > 0 && trailingFirstWord.slice(0, threshold) === cityFirstWord.slice(0, threshold)) {
    return before.trim()
  }
  return name
}

const TYPE_ABBREVIATIONS: [RegExp, string][] = [
  [/Szkoła Podstawowa/i, "SP"],
  [/Liceum Ogólnokształcące/i, "LO"],
  [/Branżowa Szkoła I Stopnia/i, "Szkoła Branżowa I"],
  [/Branżowa Szkoła II Stopnia/i, "Szkoła Branżowa II"],
]

export function shortenSchoolName(name: string, city: string | null): string {
  let result = stripTrailingCityClause(name, city)
  result = toDisplayCase(result)
  for (const [pattern, replacement] of TYPE_ABBREVIATIONS) {
    result = result.replace(pattern, replacement)
  }
  return result
}
