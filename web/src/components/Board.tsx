import { Chessboard } from 'react-chessboard'
import { epdFields } from '../epd'

// Read-only board. react-chessboard only reads the placement field, so raw EPD works.
export default function Board({ epd }: { epd: string }) {
  const fields = epdFields(epd)

  return (
    <div className="board-panel">
      <div className="board-wrap">
        <Chessboard options={{ position: epd, allowDragging: false }} />
      </div>
      <table className="epd-facts">
        <tbody>
          <tr>
            <td>side to move</td>
            <td>{fields.sideToMove === 'w' ? 'white' : 'black'}</td>
          </tr>
          <tr>
            <td>castling</td>
            <td>{fields.castling}</td>
          </tr>
          <tr>
            <td>en passant</td>
            <td>{fields.enPassant}</td>
          </tr>
          <tr>
            <td>epd</td>
            <td className="mono">{epd}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
