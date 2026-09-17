"""Four-connected scanline discovery, independent of brush realization."""


def flood_spans(width, height, seed, eligible):
    """Return disjoint (y, left, right) spans; right is exclusive.

    Mark whole runs when discovered, then search their vertical neighbours.
    No recursion and no dependence on whether painting changes a pixel.
    ``eligible`` must describe the unchanged source surface and clip.
    """
    visited = bytearray(width * height)
    spans = []
    pending = [seed]

    def available(x, y):
        return 0 <= x < width and 0 <= y < height and not visited[y * width + x] and eligible(x, y)

    while pending:
        x, y = pending.pop()
        if not available(x, y):
            continue
        left, right = x, x + 1
        while available(left - 1, y):
            left -= 1
        while available(right, y):
            right += 1
        visited[y * width + left : y * width + right] = b"\1" * (right - left)
        spans.append((y, left, right))
        for neighbour in (y - 1, y + 1):
            in_run = False
            for column in range(left, right):
                match = available(column, neighbour)
                if match and not in_run:
                    pending.append((column, neighbour))
                in_run = match
    return spans
