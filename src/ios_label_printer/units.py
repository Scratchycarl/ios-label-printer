MM_PER_INCH = 25.4
POINTS_PER_INCH = 72.0


def mm_to_px(mm: float, dpi: float) -> int:
    return max(1, round(mm / MM_PER_INCH * dpi))


def px_to_mm(px: float, dpi: float) -> float:
    return px * MM_PER_INCH / dpi


def pt_to_px(points: float, dpi: float) -> int:
    return max(1, round(points / POINTS_PER_INCH * dpi))
