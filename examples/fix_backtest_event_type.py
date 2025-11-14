"""Patch backtest tick .npz files so that depth events use DEPTH_EVENT instead of DEPTH_BBO_EVENT.

This is intended for older exports that used DEPTH_BBO_EVENT. New exports from
MT5DataExporter already use DEPTH_EVENT, so this script is mainly for
backfilling existing data files under data/backtest.

Usage (from project root):
    python examples/fix_backtest_event_type.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import hftbacktest.types as hbt_types


# Low bits of ev encode the base event type; higher bits are flags (exchange, side).
_BASE_TYPE_MASK = (1 << 4) - 1  # 0b1111


def _patch_file(path: Path) -> None:
    npz = np.load(path)
    if "data" not in npz:
        print(f"  -> skipped (no 'data' key in {path.name})")
        return

    data = npz["data"]
    ev = data["ev"]

    unique_before = np.unique(ev)
    print(
        f"  ev unique before: {unique_before[:10]} "
        f"(total {len(unique_before)})"
    )

    base_type = ev & _BASE_TYPE_MASK

    # Step 1: convert DEPTH_BBO_EVENT -> DEPTH_EVENT (if present)
    bbo_mask = base_type == hbt_types.DEPTH_BBO_EVENT
    bbo_count = int(bbo_mask.sum())
    if bbo_count:
        delta = np.uint64(hbt_types.DEPTH_BBO_EVENT - hbt_types.DEPTH_EVENT)
        ev[bbo_mask] = ev[bbo_mask] - delta

    # Step 2: drop EXCH_EVENT flag on depth events so they match Binance converters
    depth_mask = base_type == hbt_types.DEPTH_EVENT
    exch_mask = (ev & hbt_types.EXCH_EVENT) != 0
    depth_exch_mask = depth_mask & exch_mask
    depth_exch_count = int(depth_exch_mask.sum())
    if depth_exch_count:
        ev[depth_exch_mask] = ev[depth_exch_mask] - np.uint64(
            hbt_types.EXCH_EVENT
        )

    if not (bbo_count or depth_exch_count):
        print("  -> no convertible depth events found; skipping.")
        return

    np.savez_compressed(path, data=data)

    npz2 = np.load(path)
    ev2 = npz2["data"]["ev"]
    unique_after = np.unique(ev2)
    print(
        f"  ev unique after: {unique_after[:10]} "
        f"(total {len(unique_after)}) (patched {bbo_count} BBO->DEPTH, "
        f"cleared EXCH on {depth_exch_count} depth events)"
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

