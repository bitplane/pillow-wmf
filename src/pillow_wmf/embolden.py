"""TrueType synthetic emboldening as the native rasterizer applies it.

GDI simulates a bold weight on a face that lacks one by moving outline points
in 26.6 device space, y up, after grid fitting and before scan conversion:

- each point's two adjacent edges are offset horizontally (and vertically,
  for a vertical strength) by the strength, toward the side they face;
- the point moves to where the offset edges meet, clamped to the strength;
- the whole outline then moves by the strength's left and lower parts.

A one-pixel horizontal strength takes a shortcut: edges running downward (the
right-hand side of the font's clockwise outlines) move right by the
strength's right part, edges running upward stay. Contours with fewer than
three points stay as they are, and consecutive coincident points move
together. All arithmetic is the rasterizer's integer arithmetic.
"""


def _div(divisor: int, value: int) -> int:
    """``value / divisor`` rounded half away from zero (the rasterizer's CompDiv)."""
    half = _trunc_div(divisor, 2) if divisor else 0
    value += half if (divisor < 0) == (value < 0) else -half
    if not divisor:
        return 0x7FFFFFFF + (value < 0)
    return _trunc_div(value, divisor)


def _mul26_6(a: int, b: int) -> int:
    if -0xB505 < a < 0xB505 and -0xB505 < b < 0xB505:
        return (a * b + 0x20) >> 6
    product = (abs(a) * abs(b) + 0x20) >> 6
    return -product if (a < 0) != (b < 0) else product


def _frac_sqrt(value: int) -> int:
    """The square root of a 2.30 fraction, as a 2.30 fraction."""
    if value < 0:
        return -0x80000000
    mask = 0xFFFFFFFF
    bit = 0x10000000
    root = 0x40000000 if value >= 0x40000000 else 0
    remainder = (value - 0x40000000) & mask if value >= 0x40000000 else value
    while True:
        last = remainder
        if bit + root <= last:
            last = (last - (bit + root)) & mask
            root = (root + bit * 2) & mask
        remainder = (last * 2) & mask
        bit >>= 1
        if not bit:
            break
    if root < remainder:
        difference = (remainder - root) & mask
        root += 1
        last = (difference * 2 - 1) & mask
    else:
        last = (last << 2) & mask
    return root + (root < last)


def _trunc_div(value: int, divisor: int) -> int:
    quotient = abs(value) // abs(divisor)
    return quotient if (value < 0) == (divisor < 0) else -quotient


def _normalize(x: int, y: int) -> tuple[int, int]:
    """A unit vector in 2.14 (the interpreter's itrp_Normalize)."""
    if not x and not y:
        return 0x4000, 0
    if -0x7FFF <= x < 0x7FFF and -0x7FFF <= y <= 0x7FFE:
        shift, total = 15, x * x + y * y
        while total < 0x20000000:
            total <<= 2
            shift += 1
        x, y = x << shift, y << shift
    else:
        while x < 0x20000000:
            if x < -0x1FFFFFFF or not -0x1FFFFFFF <= y <= 0x1FFFFFFF:
                break
            x, y = x * 2, y * 2
        total = ((y * y + 0x20000000) >> 30) + ((x * x + 0x20000000) >> 30)
    root = _frac_sqrt(total)
    if not root:
        return 0x7FFF, 0x7FFF
    half = root // 2

    def component(value):
        rounded = value * 0x40000000 + (half if value >= 0 else -half)
        return (_trunc_div(rounded, root) + 0x8000) >> 16

    return component(x), component(y)


def _intersect(p0, p1, q0, q1) -> tuple[int, int]:
    """Where line p0-p1 meets line q0-q1 (the rasterizer's Intersect26Dot6)."""
    pdx, pdy = p1[0] - p0[0], p1[1] - p0[1]
    qdx, qdy = q1[0] - q0[0], q1[1] - q0[1]
    if not pdy:
        if not qdx:
            return q0[0], p0[1]
        numerator, denominator = q0[1] - p0[1], -qdy
    elif not pdx:
        if not qdy:
            return p0[0], q0[1]
        numerator, denominator = q0[0] - p0[0], -qdx
    elif abs(pdx) < abs(pdy):
        numerator = _div(pdy, (q0[1] - p0[1]) * pdx) - q0[0] + p0[0]
        denominator = qdx - _div(pdy, qdy * pdx)
    else:
        numerator = (q0[1] - p0[1]) - _div(pdx, (q0[0] - p0[0]) * pdy)
        denominator = _div(pdx, qdx * pdy) - qdy
    if abs(denominator) < 0x11:
        return (q0[0] + p1[0]) >> 1, (p1[1] + q0[1]) >> 1
    return q0[0] + _div(denominator, qdx * numerator), q0[1] + _div(denominator, qdy * numerator)


def embolden(contours, x_strength: int, y_strength: int = 0, *, grid_fitted: bool):
    """Embolden contours of (x, y, on) 26.6 points, y up, clockwise outside.

    ``x_strength`` and ``y_strength`` are whole pixels. A grid-fitted outline
    puts a strength's odd pixel on the right and top; otherwise each side
    takes half.
    """
    # ``top`` offsets edges facing up and ``bottom`` edges facing down, and the
    # outline then moves up by ``bottom``: the odd pixel goes to the lower half.
    if grid_fitted:
        left, top = (x_strength >> 1) << 6, (y_strength >> 1) << 6
        right, bottom = (x_strength - (x_strength >> 1)) * 64, (y_strength - (y_strength >> 1)) * 64
    else:
        left = right = x_strength << 5
        bottom = top = y_strength << 5
    simple = x_strength == 1
    result = []
    for contour in contours:
        count = len(contour)
        if count < 3:
            result.append(list(contour))
            continue
        moved = [list(point) for point in contour]
        index = 0
        while index < count:
            current = contour[index][:2]
            last = index
            while last + 1 < count and contour[last + 1][:2] == current:
                last += 1
            previous = contour[index - 1][:2] if index else contour[-1][:2]
            following = contour[last + 1][:2] if last + 1 < count else contour[0][:2]
            point = _embolden_point(previous, current, following, simple, left, right, bottom, top)
            for k in range(index, last + 1):
                moved[k][0], moved[k][1] = point
            index = last + 1
        result.append([tuple(point) for point in moved])
    return result


def _embolden_point(previous, current, following, simple, left, right, bottom, top):
    # Each edge's left normal, (-dy, dx), faces outward on a clockwise outline.
    first = (previous[1] - current[1], current[0] - previous[0])
    second = (current[1] - following[1], following[0] - current[0])
    if simple:
        start, end = previous, following
        one = (current[0] + (right if first[0] > 0 else 0), current[1])
        two = (current[0] + (right if second[0] > 0 else 0), current[1])
    else:

        def offset(normal):
            nx, ny = (component >> 8 for component in _normalize(*normal))
            return _mul26_6(nx, right if nx >= 1 else left), _mul26_6(ny, top if ny >= 0 else bottom)

        (ax, ay), (bx, by) = offset(first), offset(second)
        start, one = (previous[0] + ax, previous[1] + ay), (current[0] + ax, current[1] + ay)
        two, end = (current[0] + bx, current[1] + by), (following[0] + bx, following[1] + by)
    if one == two:
        x, y = two
    else:
        x, y = _intersect(start, one, two, end)
        dx, dy = x - current[0], y - current[1]
        if right < dx:
            x = current[0] + right
        if dx < -left:
            x = current[0] - left
        if dy < -bottom:
            y = current[1] - bottom
        if top < dy:
            y = current[1] + bottom  # (sic) the rasterizer clamps upward moves by the lower half
    return x + left, y + bottom
