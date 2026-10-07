// Splits the server's normalized 4-field EPD for display; no chess logic here.

export interface EpdFields {
  placement: string
  sideToMove: string
  castling: string
  enPassant: string
}

export function epdFields(epd: string): EpdFields {
  const parts = epd.trim().split(/\s+/)
  if (parts.length < 4) {
    throw new Error(`not a 4-field EPD: ${JSON.stringify(epd)}`)
  }
  const [placement, sideToMove, castling, enPassant] = parts
  return { placement, sideToMove, castling, enPassant }
}
