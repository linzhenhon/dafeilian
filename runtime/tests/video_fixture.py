"""Create a tiny silent MJPEG clip for real local playback checks."""
from pathlib import Path
import struct
import sys


def make_video(path: Path) -> Path:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    def chunk(tag, data):
        return tag + struct.pack('<I', len(data)) + data + (b'\0' if len(data) % 2 else b'')

    width, height, fps, count = 320, 180, 8, 64
    frames = []
    for index in range(count):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor('#173844'))
        painter = QPainter(image)
        painter.setPen(QColor('#B6DBC1'))
        painter.setBrush(QColor('#8FC5B4'))
        painter.drawEllipse(QRectF(32 + index * 3, 50, 62, 62))
        painter.setBrush(QColor('#416B79'))
        painter.drawRoundedRect(QRectF(28, 134, 264, 15), 7, 7)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, 'JPEG', 85):
            raise RuntimeError('JPEG encoder unavailable')
        frames.append(bytes(data))
    largest = max(map(len, frames))
    avih = struct.pack('<14I', 1_000_000 // fps, largest * fps, 0, 0x10, count, 0, 1, largest,
                       width, height, 0, 0, 0, 0)
    strh = struct.pack('<4s4sIHH8I4h', b'vids', b'MJPG', 0, 0, 0, 0, 1, fps, 0, count,
                       largest, 0xFFFFFFFF, 0, 0, 0, width, height)
    strf = struct.pack('<IiiHH4sIiiII', 40, width, height, 1, 24, b'MJPG', width * height * 3, 0, 0, 0, 0)
    header = chunk(b'LIST', b'hdrl' + chunk(b'avih', avih) + chunk(b'LIST', b'strl' + chunk(b'strh', strh) + chunk(b'strf', strf)))
    movie, index, offset = bytearray(), bytearray(), 4
    for frame in frames:
        data = chunk(b'00dc', frame)
        movie.extend(data)
        index.extend(struct.pack('<4sIII', b'00dc', 0x10, offset, len(frame)))
        offset += len(data)
    content = b'AVI ' + header + chunk(b'LIST', b'movi' + bytes(movie)) + chunk(b'idx1', bytes(index))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(chunk(b'RIFF', content))
    return path


if __name__ == '__main__':
    make_video(Path(sys.argv[1]))
