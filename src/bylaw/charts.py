"""Stacked bar charts as PNG, drawn with the standard library only (ADR 0022).

The report runs inside the Action, where a headless browser or a plotting library would be a heavy
install for two small charts. A chart here is a palette image: rectangles and a 5 by 7 bitmap font,
compressed with zlib and framed as PNG by hand.
"""

import struct
import zlib
from collections.abc import Sequence

# Colours per theme. Series colours are the Okabe-Ito set, which stays apart for the common kinds of
# colour blindness, lightened for the dark background.
THEMES: dict[str, dict[str, str]] = {
    "light": {
        "background": "#ffffff",
        "text": "#1f2328",
        "fixed": "#009e73",
        "met": "#009e73",
        "muted": "#e69f00",
        "partial": "#e69f00",
        "resolved": "#0072b2",
        "suppressed": "#8c959f",
        "not assessed": "#8c959f",
        "open at close": "#d55e00",
        "missing": "#d55e00",
    },
    "dark": {
        "background": "#0d1117",
        "text": "#e6edf3",
        "fixed": "#3ec79b",
        "met": "#3ec79b",
        "muted": "#f5b83d",
        "partial": "#f5b83d",
        "resolved": "#56b4e9",
        "suppressed": "#6e7681",
        "not assessed": "#6e7681",
        "open at close": "#f0803c",
        "missing": "#f0803c",
    },
}

_WIDTH = 720
_SCALE = 2
_CHAR = 6 * _SCALE  # five pixels and a gap
_TEXT = 7 * _SCALE
_MARGIN = 16
_ROW = 30
_BAR = 18
_SWATCH = 12
# Upper case 5 by 7 glyphs, rows top to bottom; a character without one is drawn as a space.
_FONT = {
    "A": ".###./#...#/#...#/#####/#...#/#...#/#...#",
    "B": "####./#...#/#...#/####./#...#/#...#/####.",
    "C": ".###./#...#/#..../#..../#..../#...#/.###.",
    "D": "####./#...#/#...#/#...#/#...#/#...#/####.",
    "E": "#####/#..../#..../####./#..../#..../#####",
    "F": "#####/#..../#..../####./#..../#..../#....",
    "G": ".###./#...#/#..../#.###/#...#/#...#/.####",
    "H": "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    "I": ".###./..#../..#../..#../..#../..#../.###.",
    "J": "..###/...#./...#./...#./...#./#..#./.##..",
    "K": "#...#/#..#./#.#../##.../#.#../#..#./#...#",
    "L": "#..../#..../#..../#..../#..../#..../#####",
    "M": "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#",
    "N": "#...#/#...#/##..#/#.#.#/#..##/#...#/#...#",
    "O": ".###./#...#/#...#/#...#/#...#/#...#/.###.",
    "P": "####./#...#/#...#/####./#..../#..../#....",
    "Q": ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",
    "R": "####./#...#/#...#/####./#.#../#..#./#...#",
    "S": ".####/#..../#..../.###./....#/....#/####.",
    "T": "#####/..#../..#../..#../..#../..#../..#..",
    "U": "#...#/#...#/#...#/#...#/#...#/#...#/.###.",
    "V": "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    "W": "#...#/#...#/#...#/#.#.#/#.#.#/#.#.#/.#.#.",
    "X": "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    "Y": "#...#/#...#/.#.#./..#../..#../..#../..#..",
    "Z": "#####/....#/...#./..#../.#.../#..../#####",
    "0": ".###./#...#/#..##/#.#.#/##..#/#...#/.###.",
    "1": "..#../.##../..#../..#../..#../..#../.###.",
    "2": ".###./#...#/....#/...#./..#../.#.../#####",
    "3": "#####/...#./..#../...#./....#/#...#/.###.",
    "4": "...#./..##./.#.#./#..#./#####/...#./...#.",
    "5": "#####/#..../####./....#/....#/#...#/.###.",
    "6": "..##./.#.../#..../####./#...#/#...#/.###.",
    "7": "#####/....#/...#./..#../.#.../.#.../.#...",
    "8": ".###./#...#/#...#/.###./#...#/#...#/.###.",
    "9": ".###./#...#/#...#/.####/....#/...#./.##..",
    "-": "...../...../...../#####/...../...../.....",
    "%": "##.../##..#/...#./..#../.#.../#..##/...##",
    ".": "...../...../...../...../...../.##../.##..",
    ":": "...../.##../.##../...../.##../.##../.....",
    "/": "...../....#/...#./..#../.#.../#..../.....",
}


def stacked_bars(rows: Sequence[tuple[str, Sequence[int]]], series: Sequence[str], theme: str) -> bytes:
    """A horizontal stacked bar per row, labelled on the left with its total on the right, and a legend
    of the series on top. Bars share one scale, so their lengths compare."""
    colours = THEMES[theme]
    palette = ["background", "text", *series]
    label_width = max((len(label) for label, _ in rows), default=0) * _CHAR + _MARGIN
    totals = [sum(values) for _, values in rows]
    value_width = max((len(str(t)) for t in totals), default=1) * _CHAR + _MARGIN
    height = 2 * _MARGIN + _TEXT + _MARGIN + len(rows) * _ROW
    canvas = _Canvas(_WIDTH, height)

    x = _MARGIN
    for index, name in enumerate(series, start=2):
        canvas.rect(x, _MARGIN + 1, _SWATCH, _SWATCH, index)
        canvas.text(x + _SWATCH + 6, _MARGIN, name, 1)
        x += _SWATCH + 6 + len(name) * _CHAR + 18

    bar_left = _MARGIN + label_width
    span = _WIDTH - bar_left - value_width - _MARGIN
    largest = max(totals, default=0) or 1
    for row, ((label, values), total) in enumerate(zip(rows, totals, strict=True)):
        top = 2 * _MARGIN + _TEXT + row * _ROW
        canvas.text(_MARGIN, top + (_BAR - _TEXT) // 2, label, 1)
        x = bar_left
        for index, value in enumerate(values, start=2):
            width = round(span * value / largest)
            canvas.rect(x, top, width, _BAR, index)
            x += width
        canvas.text(x + 8, top + (_BAR - _TEXT) // 2, str(total), 1)
    return canvas.png([_rgb(colours[name]) for name in palette])


class _Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height)  # palette index 0, the background

    def rect(self, x: int, y: int, width: int, height: int, colour: int) -> None:
        width = max(0, min(width, self.width - x))
        for row in range(y, min(y + height, self.height)):
            start = row * self.width + x
            self.pixels[start : start + width] = bytes([colour]) * width

    def text(self, x: int, y: int, text: str, colour: int) -> None:
        for char in text.upper():
            for dy, line in enumerate(_FONT.get(char, "").split("/")):
                for dx, dot in enumerate(line):
                    if dot == "#":
                        self.rect(x + dx * _SCALE, y + dy * _SCALE, _SCALE, _SCALE, colour)
            x += _CHAR

    def png(self, palette: Sequence[tuple[int, int, int]]) -> bytes:
        rows = b"".join(
            b"\x00" + self.pixels[y * self.width : (y + 1) * self.width] for y in range(self.height)
        )
        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 3, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"PLTE", b"".join(bytes(colour) for colour in palette))
            + _chunk(b"IDAT", zlib.compress(rows, 9))
            + _chunk(b"IEND", b"")
        )


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _rgb(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)
