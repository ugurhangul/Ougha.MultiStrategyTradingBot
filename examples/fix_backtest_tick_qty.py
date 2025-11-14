"""Patch backtest tick .npz files so that qty is strictly positive.

This is a small utility for development/testing environments. Some MT5
brokers report zero volume on quote ticks, which results in depth levels
with zero quantity. hftbacktest treats such levels as empty and the
market depth book remains NaN (no best bid/ask).

Running this script updates existing tick .npz files under data/backtest
so that any non-finite or non-positive quantities are replaced with 1.0.

Usage (from project root):
    python examples/fix_backtest_tick_qty.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _patch_file(path: Path) -> None:
    npz = np.load(path)
    if "data" not in npz:
        print(f"  -> skipped (no 'data' key in {path.name})")
        return

    data = npz["data"]
    qty = data["qty"]

    before_min = float(qty.min())
    before_max = float(qty.max())
    print(f"  qty before: min={before_min}, max={before_max}")

    mask = ~np.isfinite(qty) | (qty <= 0.0)
    replaced = int(mask.sum())
    if replaced == 0:
        print("  -> no non-positive quantities; skipping.")
        return

    data["qty"][mask] = 1.0
    np.savez_compressed(path, data=data)

    npz2 = np.load(path)
    qty2 = npz2["data"]["qty"]
    after_min = float(qty2.min())
    after_max = float(qty2.max())
    print(
        f"  qty after: min={after_min}, max={after_max} "
        f"(replaced {replaced} entries)"
    )


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data" / "backtest"

    print(f"Scanning {data_dir} for *tick*.npz files...")
    tick_files = sorted(data_dir.glob("*tick*.npz"))

    if not tick_files:
        print("No tick data files found.")
        return

    for path in tick_files:
        print(f"Processing {path.name}...")
        try:
            _patch_file(path)
        except Exception as exc:  # pragma: no cover - safety net
            print(f"  -> error while patching: {exc}")


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()

