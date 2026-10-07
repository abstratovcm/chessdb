import { describe, expect, it } from 'vitest'
import { epdFields } from './epd'

describe('epdFields', () => {
  it('splits a 4-field EPD into named fields', () => {
    const fields = epdFields('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -')
    expect(fields).toEqual({
      placement: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR',
      sideToMove: 'w',
      castling: 'KQkq',
      enPassant: '-',
    })
  })

  it('trims surrounding whitespace and collapses runs of spaces', () => {
    const fields = epdFields('  8/8/8/8/8/8/8/8  b  -  -  ')
    expect(fields.sideToMove).toBe('b')
    expect(fields.enPassant).toBe('-')
  })

  it('throws on a string with fewer than 4 fields', () => {
    expect(() => epdFields('8/8/8/8/8/8/8/8 w')).toThrow(/4-field EPD/)
  })
})
