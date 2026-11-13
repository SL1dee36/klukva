"""
Self-contained pure-Python QR Code SVG generator (Byte mode, EC Level L, Versions 1-10).
Zero external dependencies — works identically in local dev and remote server venvs.
"""

from typing import List, Tuple

# GF(256) with primitive polynomial 0x11d
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _EXP[_i + 255] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11d


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_gen_poly(degree: int) -> List[int]:
    g = [1]
    for i in range(degree):
        ng = [0] * (len(g) + 1)
        a = _EXP[i]
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= _gf_mul(c, a)
        g = ng
    return g


def _rs_encode(data: List[int], ec_count: int) -> List[int]:
    gen = _rs_gen_poly(ec_count)
    res = list(data) + [0] * ec_count
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# Version specs for EC Level L:
# (version, total_codewords, ec_per_block, blocks_g1, data_g1, blocks_g2, data_g2, alignment_positions)
_VERSION_SPECS: List[Tuple[int, int, int, int, int, int, int, List[int]]] = [
    (1, 26, 7, 1, 19, 0, 0, []),
    (2, 44, 10, 1, 34, 0, 0, [6, 18]),
    (3, 70, 15, 1, 55, 0, 0, [6, 22]),
    (4, 100, 20, 1, 80, 0, 0, [6, 26]),
    (5, 134, 26, 1, 108, 0, 0, [6, 30]),
    (6, 172, 18, 2, 68, 0, 0, [6, 34]),
    (7, 196, 20, 2, 78, 0, 0, [6, 22, 38]),
    (8, 242, 24, 2, 97, 0, 0, [6, 24, 42]),
    (9, 292, 30, 2, 116, 0, 0, [6, 26, 46]),
    (10, 346, 18, 2, 68, 2, 69, [6, 28, 50]),
]


def _encode_data(payload: bytes) -> Tuple[int, List[int]]:
    n = len(payload)
    for spec in _VERSION_SPECS:
        ver, total_cw, ec_cw, b1, d1, b2, d2, _ = spec
        data_cw = b1 * d1 + b2 * d2
        cc_bits = 8 if ver <= 9 else 16
        cap_bits = data_cw * 8
        needed_bits = 4 + cc_bits + n * 8
        if needed_bits <= cap_bits:
            bits: List[int] = []

            def push(val: int, length: int) -> None:
                for shift in range(length - 1, -1, -1):
                    bits.append((val >> shift) & 1)

            push(0b0100, 4)  # Byte mode
            push(n, cc_bits)
            for b in payload:
                push(b, 8)
            term = min(4, cap_bits - len(bits))
            push(0, term)
            while len(bits) % 8 != 0:
                bits.append(0)
            pad_bytes = [0xEC, 0x11]
            pi = 0
            while len(bits) < cap_bits:
                push(pad_bytes[pi % 2], 8)
                pi += 1

            data_bytes = [
                sum(bits[i + j] << (7 - j) for j in range(8))
                for i in range(0, len(bits), 8)
            ]

            blocks_data: List[List[int]] = []
            blocks_ec: List[List[int]] = []
            idx = 0
            for _ in range(b1):
                blk = data_bytes[idx:idx + d1]
                idx += d1
                blocks_data.append(blk)
                blocks_ec.append(_rs_encode(blk, ec_cw))
            for _ in range(b2):
                blk = data_bytes[idx:idx + d2]
                idx += d2
                blocks_data.append(blk)
                blocks_ec.append(_rs_encode(blk, ec_cw))

            out: List[int] = []
            max_d = max(d1, d2)
            for i in range(max_d):
                for blk in blocks_data:
                    if i < len(blk):
                        out.append(blk[i])
            for i in range(ec_cw):
                for ec in blocks_ec:
                    out.append(ec[i])
            return ver, out
    raise ValueError("Payload too long for QR version 1-10")


def _build_matrix(ver: int, codewords: List[int]) -> List[List[int]]:
    size = ver * 4 + 17
    # -1 = empty, 0 = white, 1 = black
    m = [[-1] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def set_mod(r: int, c: int, val: int) -> None:
        if 0 <= r < size and 0 <= c < size:
            m[r][c] = val
            func[r][c] = True

    def place_finder(r0: int, c0: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if 0 <= r < size and 0 <= c < size:
                    in_outer = 0 <= dr <= 6 and 0 <= dc <= 6
                    on_border = dr in (0, 6) or dc in (0, 6)
                    in_inner = 2 <= dr <= 4 and 2 <= dc <= 4
                    val = 1 if (in_outer and (on_border or in_inner)) else 0
                    set_mod(r, c, val)

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        v = 1 if i % 2 == 0 else 0
        set_mod(6, i, v)
        set_mod(i, 6, v)

    # Dark module
    set_mod(size - 8, 8, 1)

    # Alignment patterns
    align_pos = _VERSION_SPECS[ver - 1][7]
    for r in align_pos:
        for c in align_pos:
            if func[r][c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = 1 if (max(abs(dr), abs(dc)) in (0, 2)) else 0
                    set_mod(r + dr, c + dc, val)

    # Reserve format info areas
    for i in range(9):
        if i != 6:
            func[8][i] = True
            func[i][8] = True
    for i in range(8):
        func[8][size - 1 - i] = True
        func[size - 1 - i][8] = True

    # Version info for ver >= 7
    if ver >= 7:
        v_bits = ver << 12
        rem = v_bits
        for i in range(17, 11, -1):
            if (rem >> i) & 1:
                rem ^= 0x1F25 << (i - 12)
        v_info = v_bits | rem
        for i in range(18):
            bit = (v_info >> i) & 1
            r = i // 3
            c = size - 11 + (i % 3)
            set_mod(r, c, bit)
            set_mod(c, r, bit)

    # Place data bits
    bits: List[int] = []
    for cw in codewords:
        for shift in range(7, -1, -1):
            bits.append((cw >> shift) & 1)

    bit_idx = 0
    up = True
    c = size - 1
    while c > 0:
        if c == 6:
            c -= 1
        rows = range(size - 1, -1, -1) if up else range(size)
        for r in rows:
            for dc in (0, -1):
                cc = c + dc
                if not func[r][cc]:
                    b = bits[bit_idx] if bit_idx < len(bits) else 0
                    bit_idx += 1
                    m[r][cc] = b
        up = not up
        c -= 2

    # Try all 8 masks and pick lowest penalty
    best_mat = None
    best_pen = 10 ** 9
    for mask_id in range(8):
        cand = [row[:] for row in m]
        for r in range(size):
            for col in range(size):
                if func[r][col]:
                    continue
                if _mask_cond(mask_id, r, col):
                    cand[r][col] ^= 1
        _apply_format(cand, mask_id)
        pen = _penalty(cand)
        if pen < best_pen:
            best_pen = pen
            best_mat = cand

    return best_mat  # type: ignore[return-value]


def _mask_cond(mask_id: int, r: int, c: int) -> bool:
    if mask_id == 0:
        return (r + c) % 2 == 0
    if mask_id == 1:
        return r % 2 == 0
    if mask_id == 2:
        return c % 3 == 0
    if mask_id == 3:
        return (r + c) % 3 == 0
    if mask_id == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask_id == 5:
        return ((r * c) % 2 + (r * c) % 3) == 0
    if mask_id == 6:
        return (((r * c) % 2 + (r * c) % 3) % 2) == 0
    return (((r + c) % 2 + (r * c) % 3) % 2) == 0


def _apply_format(m: List[List[int]], mask_id: int) -> None:
    size = len(m)
    # EC level L = 01
    data = (0b01 << 3) | mask_id
    rem = data << 10
    for i in range(14, 9, -1):
        if (rem >> i) & 1:
            rem ^= 0x537 << (i - 10)
    fmt = ((data << 10) | rem) ^ 0x5412

    for i in range(6):
        bit = (fmt >> (14 - i)) & 1
        m[8][i] = bit
        m[size - 1 - i][8] = bit
    m[8][7] = (fmt >> 8) & 1
    m[8][8] = (fmt >> 7) & 1
    m[7][8] = (fmt >> 6) & 1
    for i in range(6):
        m[5 - i][8] = (fmt >> (5 - i)) & 1

    m[size - 7][8] = (fmt >> 8) & 1
    for i in range(8):
        m[8][size - 8 + i] = (fmt >> (7 - i)) & 1


def _penalty(m: List[List[int]]) -> int:
    size = len(m)
    pen = 0
    # Rule 1: 5+ consecutive same color
    for r in range(size):
        run_c = m[r][0]
        run_len = 1
        for c in range(1, size):
            if m[r][c] == run_c:
                run_len += 1
            else:
                if run_len >= 5:
                    pen += 3 + (run_len - 5)
                run_c = m[r][c]
                run_len = 1
        if run_len >= 5:
            pen += 3 + (run_len - 5)
    for c in range(size):
        run_c = m[0][c]
        run_len = 1
        for r in range(1, size):
            if m[r][c] == run_c:
                run_len += 1
            else:
                if run_len >= 5:
                    pen += 3 + (run_len - 5)
                run_c = m[r][c]
                run_len = 1
        if run_len >= 5:
            pen += 3 + (run_len - 5)
    # Rule 2: 2x2 blocks
    for r in range(size - 1):
        for c in range(size - 1):
            v = m[r][c]
            if m[r][c + 1] == v and m[r + 1][c] == v and m[r + 1][c + 1] == v:
                pen += 3
    return pen


def make_qr_svg(text: str, box_size: int = 5, border: int = 2) -> str:
    """Return a clean, self-contained inline SVG string for the given text."""
    ver, cw = _encode_data(text.encode("utf-8"))
    mat = _build_matrix(ver, cw)
    n = len(mat)
    dim = (n + border * 2) * box_size
    rects = []
    for r, row in enumerate(mat):
        for c, val in enumerate(row):
            if val == 1:
                x = (c + border) * box_size
                y = (r + border) * box_size
                rects.append(f'<rect x="{x}" y="{y}" width="{box_size}" height="{box_size}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" '
        f'width="180" height="180" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<g fill="#111111">{"".join(rects)}</g></svg>'
    )

