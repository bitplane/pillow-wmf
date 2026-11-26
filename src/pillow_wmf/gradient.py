"""Native GradientFill triangle rasterization in 48-bit fixed point.

Colours are 16-bit channels clamped to 0xff00. Each channel's plane is held
as a 64-bit value with 48 fractional bits: its per-pixel and per-row steps
are the plane's slopes divided by the triangle's doubled area and floored,
and its value at the top vertex carries a half-unit rounding bias. Rows run
from the top vertex to the row before the bottom one. Each edge is walked
with an integer error term; a row starts at the smallest x any edge reaches
on it, with that edge's colour, and ends before the largest. A horizontal
edge instead starts its row at its left vertex with the vertex's exact
colour, without the bias. Pixels step one x at a time and keep each
channel's top 8 bits.
"""

import math
import struct

MASK = (1 << 64) - 1
ONE = 1 << 48


def _int32(value):
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value >= 1 << 31 else value


def _trunc_div(a, b):
    quotient = abs(a) // abs(b)
    return quotient if (a < 0) == (b < 0) else -quotient


def _mdiv64(a, b, c):
    """Floor of a * b / c for b >= 0 and c > 0."""
    if a == 0 or b == 0:
        return 0
    if a < 0:
        return -((-a * b - 1) // c) - 1
    return a * b // c


def _gradient(p1, p2, p3):
    """Per-channel (dx step, dy step, value at p1) in 48-bit fixed point."""
    dx2, dx3 = p2[0] - p1[0], p3[0] - p1[0]
    dy2, dy3 = p2[1] - p1[1], p3[1] - p1[1]
    area = dy3 * dx2 - dy2 * dx3
    bias = min(dy3, min(dy2, 0)) + min(dx3, min(dx2, 0))
    size = abs(area)
    quotient, remainder = divmod(ONE, size)
    half = (size >> 1) + 1
    channels = []
    for i in range(2, 5):
        c1, c2, c3 = p1[i], p2[i], p3[i]
        along_y = _int32((c3 - c1) * dx2 - (c2 - c1) * dx3)
        along_x = _int32((c2 - c1) * dy3 - (c3 - c1) * dy2)
        if area < 0:
            along_x, along_y = -along_x, -along_y
        step_x = _mdiv64(along_x, remainder, size) + quotient * along_x
        step_y = _mdiv64(along_y, remainder, size) + quotient * along_y
        origin = (c1 << 48) + quotient * half + bias + _trunc_div(remainder * half - bias - 1, size)
        channels.append((step_x, step_y, origin))
    return channels


def triangle_spans(corners, top_limit, bottom_limit):
    """Yield (y, left, right, colours) rows, colours a function of x giving (r, g, b)."""
    a, b, c = (tuple(v[:2]) + tuple(min(channel, 0xFF00) for channel in v[2:5]) for v in corners)
    # Native order: top vertex, then the other two with a positive area.
    low = b
    if a[1] <= b[1]:
        low, a = a, b
    bottom = c
    if c[1] < a[1]:
        bottom, a = a, c
    top = a if a[1] < low[1] else low
    middle = low if a[1] < low[1] else a

    def area(p, q, r):
        return (q[1] - r[1]) * (p[0] - r[0]) - (p[1] - r[1]) * (q[0] - r[0])

    signed = area(top, middle, bottom)
    if signed == 0:
        return
    if signed < 0:
        middle, bottom = bottom, middle
    first_row = max(top[1], top_limit)
    last_row = min(max(middle[1], bottom[1]), bottom_limit)
    if last_row <= first_row:
        return
    rows = [[0x7FFFFFFF, -0x80000000, None] for _ in range(last_row - first_row)]
    gradient = _gradient(top, middle, bottom)
    ox, oy = top[0], top[1]

    def colour_at(x, y):
        return [step_x * (x - ox) + step_y * (y - oy) + origin for step_x, step_y, origin in gradient]

    for p, q in ((top, middle), (middle, bottom), (bottom, top)):
        if q[1] < p[1]:
            x0, y0, dx, dy = q[0], q[1], p[0] - q[0], p[1] - q[1]
        else:
            x0, y0, dx, dy = p[0], p[1], q[0] - p[0], q[1] - p[1]
        if dy == 0:
            if top_limit <= y0 < bottom_limit and 0 <= y0 - first_row < len(rows):
                left, right = (q, p) if q[0] < p[0] else (p, q)
                rows[y0 - first_row][:] = [left[0], right[0], [channel << 48 for channel in left[2:5]]]
            continue
        if not (y0 <= bottom_limit and top_limit <= y0 + dy):
            continue
        count = dy if y0 + dy <= bottom_limit else bottom_limit - y0
        if dx < 0:
            whole = (-1 - dx) // dy
            step, remainder = -whole - 1, (whole + 1) * dy + dx
        else:
            step, remainder = dx // dy, dx - (dx // dy) * dy
        start = remainder * y0 - 1 + (x0 + 1) * dy - y0 * dx
        offset = start // dy
        x = step * y0 + offset
        error = dy - (start - offset * dy) - 1
        colours = colour_at(x0, y0)
        row_steps = [step_y + step * step_x for step_x, step_y, _ in gradient]
        index = y0 - first_row
        for _ in range(count):
            if 0 <= index < len(rows):
                entry = rows[index]
                if x < entry[0]:
                    entry[0], entry[2] = x, list(colours)
                if entry[1] < x:
                    entry[1] = x
            colours = [value + delta for value, delta in zip(colours, row_steps, strict=True)]
            index += 1
            x += step
            error -= remainder
            if error < 0:
                x += 1
                colours = [value + step_x for value, (step_x, _, _) in zip(colours, gradient, strict=True)]
                error += dy
    steps = [step_x for step_x, _, _ in gradient]
    for offset, (left, right, start) in enumerate(rows):
        if start is None or left >= right:
            continue

        def colour(x, start=start, left=left):
            return tuple((((value + steps[i] * (x - left)) & MASK) >> 56) for i, value in enumerate(start))

        yield first_row + offset, left, right, colour


def _f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _round_float(value):
    """bFToL: a single-precision value rounded half away from zero."""
    return int(math.floor(abs(value) + 0.5)) * (1 if value >= 0 else -1)


def _midpoint(p, q):
    return [_round_float(_f32(_f32(_f32(b) - _f32(a)) * 0.5) + _f32(a)) for a, b in zip(p, q, strict=True)]


def _in_bounds(p, q, r, clip):
    xs, ys = (p[0], q[0], r[0]), (p[1], q[1], r[1])
    left, top, right, bottom = clip
    return min(xs) < right and left < max(xs) and min(ys) < bottom and top < max(ys)


SPLIT_EXTENT = 0x4000


def mesh_triangles(vertices, meshes, clip):
    """Yield each triangle's vertices in native drawing order.

    Meshes whose vertices span less than 0x4000 pixels each way draw in
    order. Larger ones are processed as a stack, last triangle first:
    triangles outside the clip bounds are dropped, and any edge longer than
    0x4000 on either axis splits the triangle at the midpoint of its longest
    edge, by single-precision arithmetic, the half on the second vertex's
    side drawn first. The stack and the added vertices have fixed capacity;
    drawing stops when either runs out. Drawing clamps the vertices' colours
    to 0xff00 in place, so later midpoints see the clamped values.
    """
    points = [list(v) for v in vertices]

    def draw(indexes):
        for index in indexes:
            points[index][2:5] = [min(channel, 0xFF00) for channel in points[index][2:5]]
        return tuple(tuple(points[index]) for index in indexes)

    xs, ys = [p[0] for p in points], [p[1] for p in points]
    if not points or (max(xs) - min(xs) < SPLIT_EXTENT and max(ys) - min(ys) < SPLIT_EXTENT):
        for mesh in meshes:
            if _in_bounds(*(points[i] for i in mesh), clip):
                yield draw(mesh)
        return
    vertex_limit = len(points) + 0x1C
    triangle_limit = len(meshes) + 0x38
    stack = [list(mesh) for mesh in meshes]
    owner = [False] * len(stack)
    vertex_count = len(points)
    count = len(stack)

    def pop():
        nonlocal count, vertex_count
        while True:
            count -= 1
            if owner[count]:
                vertex_count -= 1
            if not (count and owner[count]):
                return

    while count:
        triangle = stack[count - 1]
        if max(triangle) >= vertex_limit:
            break
        a, b, c = (points[i] for i in triangle)
        if not _in_bounds(a, b, c, clip):
            pop()
            continue
        edges = [(abs(p[0] - q[0]), abs(p[1] - q[1])) for p, q in ((a, b), (a, c), (b, c))]
        area = (b[1] - c[1]) * (a[0] - c[0]) - (a[1] - c[1]) * (b[0] - c[0])
        if all(dx <= SPLIT_EXTENT and dy <= SPLIT_EXTENT for dx, dy in edges) or area == 0:
            yield draw(triangle)
            pop()
            continue
        ab, ac, bc = (dx * dx + dy * dy for dx, dy in edges)
        i0, i1, i2 = triangle
        if ac < ab:
            # Split a-b (third c), or c-b (third a).
            near, far, third = (i0, i1, i2) if bc < ab else (i2, i1, i0)
        elif bc < ac:
            near, far, third = i0, i2, i1
        else:
            near, far, third = i2, i1, i0
        middle = _midpoint(points[near], points[far])
        middle[2:] = [value & 0xFFFF for value in middle[2:]]
        if vertex_count < len(points):
            points[vertex_count] = middle
        else:
            points.append(middle)
        # The halves are pushed above their parent, which popping the near
        # half (marked as owning the new vertex) then discards.
        index = count
        while len(stack) < index + 2:
            stack.append([0, 0, 0])
            owner.append(False)
        stack[index] = [near, third, vertex_count]
        stack[index + 1] = [far, third, vertex_count]
        owner[index + 1], owner[index] = False, True
        count = index + 2
        vertex_count += 1
        if vertex_limit < vertex_count or triangle_limit < count:
            break
