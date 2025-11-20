#!/usr/bin/env python3
"""
Detailed analysis of symbol performance by strategy type, range, and confirmations
"""

import pandas as pd
import sys

# Load the trades data
try:
    df = pd.read_csv('analysis_30days_FIXED_trades.csv')
except FileNotFoundError:
    print("Error: analysis_30days_FIXED_trades.csv not found")
    print("Please run: python analyze_trading_history.py --days 30 --output analysis_30days_FIXED.csv --format both")
    sys.exit(1)

print("="*100)
print("SYMBOL PERFORMANCE BY STRATEGY COMBINATIONS")
print("="*100)

# Create combination columns
df['strategy_range'] = df['strategy_type'] + '_' + df['range_id']
df['is_winner'] = df['profit'] > 0

# Function to calculate stats for a group
def calc_stats(group):
    return pd.Series({
        'trades': len(group),
        'wins': group['is_winner'].sum(),
        'losses': len(group) - group['is_winner'].sum(),
        'win_rate': group['is_winner'].mean() * 100,
        'net_pnl': group['profit'].sum(),
        'avg_profit': group['profit'].mean(),
        'total_profit': group[group['profit'] > 0]['profit'].sum(),
        'total_loss': group[group['profit'] <= 0]['profit'].sum(),
    })

print("\n" + "="*100)
print("1. SYMBOL PERFORMANCE BY STRATEGY TYPE (TB vs FB)")
print("="*100)

symbol_strategy = df.groupby(['symbol', 'strategy_type']).apply(calc_stats).reset_index()
symbol_strategy = symbol_strategy.sort_values(['symbol', 'net_pnl'], ascending=[True, False])

# Show symbols with both TB and FB
symbols_with_both = symbol_strategy.groupby('symbol').size()
symbols_with_both = symbols_with_both[symbols_with_both > 1].index

print("\nSymbols with BOTH True Breakout (TB) and False Breakout (FB) strategies:")
print("-"*100)
print(f"{'Symbol':<12} {'Strategy':<8} {'Trades':>7} {'Win Rate':>9} {'Net P/L':>12} {'Avg P/L':>10}")
print("-"*100)

for symbol in sorted(symbols_with_both):
    symbol_data = symbol_strategy[symbol_strategy['symbol'] == symbol]
    for _, row in symbol_data.iterrows():
        print(f"{row['symbol']:<12} {row['strategy_type']:<8} {int(row['trades']):>7} "
              f"{row['win_rate']:>8.1f}% ${row['net_pnl']:>11.2f} ${row['avg_profit']:>9.2f}")
    print()

print("\n" + "="*100)
print("2. SYMBOL PERFORMANCE BY RANGE CONFIGURATION (4H5M vs 15M1M)")
print("="*100)

symbol_range = df.groupby(['symbol', 'range_id']).apply(calc_stats).reset_index()
symbol_range = symbol_range.sort_values(['symbol', 'net_pnl'], ascending=[True, False])

# Show symbols with both ranges
symbols_with_both_ranges = symbol_range.groupby('symbol').size()
symbols_with_both_ranges = symbols_with_both_ranges[symbols_with_both_ranges > 1].index

print("\nSymbols with BOTH 4H5M and 15M1M ranges:")
print("-"*100)
print(f"{'Symbol':<12} {'Range':<8} {'Trades':>7} {'Win Rate':>9} {'Net P/L':>12} {'Avg P/L':>10}")
print("-"*100)

for symbol in sorted(symbols_with_both_ranges):
    symbol_data = symbol_range[symbol_range['symbol'] == symbol]
    for _, row in symbol_data.iterrows():
        print(f"{row['symbol']:<12} {row['range_id']:<8} {int(row['trades']):>7} "
              f"{row['win_rate']:>8.1f}% ${row['net_pnl']:>11.2f} ${row['avg_profit']:>9.2f}")
    print()

print("\n" + "="*100)
print("3. BEST STRATEGY COMBINATION FOR EACH SYMBOL (Top 30 by trades)")
print("="*100)

# Analyze all combinations
symbol_combo = df.groupby(['symbol', 'strategy_type', 'range_id']).apply(calc_stats).reset_index()

# Get top symbols by trade count
top_symbols = df['symbol'].value_counts().head(30).index

print(f"\n{'Symbol':<12} {'Best Combo':<15} {'Trades':>7} {'Win Rate':>9} {'Net P/L':>12} "
      f"{'Worst Combo':<15} {'Trades':>7} {'Win Rate':>9} {'Net P/L':>12}")
print("-"*100)

for symbol in top_symbols:
    symbol_data = symbol_combo[symbol_combo['symbol'] == symbol].copy()
    
    if len(symbol_data) == 0:
        continue
    
    # Find best and worst by net P/L
    best = symbol_data.loc[symbol_data['net_pnl'].idxmax()]
    worst = symbol_data.loc[symbol_data['net_pnl'].idxmin()]
    
    best_combo = f"{best['strategy_type']}_{best['range_id']}"
    worst_combo = f"{worst['strategy_type']}_{worst['range_id']}"
    
    print(f"{symbol:<12} {best_combo:<15} {int(best['trades']):>7} {best['win_rate']:>8.1f}% "
          f"${best['net_pnl']:>11.2f} {worst_combo:<15} {int(worst['trades']):>7} "
          f"{worst['win_rate']:>8.1f}% ${worst['net_pnl']:>11.2f}")

print("\n" + "="*100)
print("4. CONFIRMATION EFFECTIVENESS BY SYMBOL (Top 20 symbols)")
print("="*100)

# Add confirmation type column
def get_confirmation_type(row):
    if row['has_volume_confirmation'] and row['has_divergence_confirmation']:
        return 'VD'
    elif row['has_volume_confirmation']:
        return 'V'
    elif row['has_divergence_confirmation']:
        return 'D'
    else:
        return 'NC'

df['confirmation_type'] = df.apply(get_confirmation_type, axis=1)

symbol_conf = df.groupby(['symbol', 'confirmation_type']).apply(calc_stats).reset_index()

print(f"\n{'Symbol':<12} {'Confirm':<8} {'Trades':>7} {'Win Rate':>9} {'Net P/L':>12}")
print("-"*100)

for symbol in df['symbol'].value_counts().head(20).index:
    symbol_data = symbol_conf[symbol_conf['symbol'] == symbol].sort_values('net_pnl', ascending=False)
    
    for _, row in symbol_data.iterrows():
        print(f"{row['symbol']:<12} {row['confirmation_type']:<8} {int(row['trades']):>7} "
              f"{row['win_rate']:>8.1f}% ${row['net_pnl']:>11.2f}")
    print()

print("\n" + "="*100)
print("5. COMPLETE BREAKDOWN: BEST PERFORMING COMBINATIONS")
print("="*100)

# Full combination analysis
full_combo = df.groupby(['symbol', 'strategy_type', 'range_id', 'confirmation_type']).apply(calc_stats).reset_index()
full_combo['combo'] = (full_combo['strategy_type'] + '_' + full_combo['range_id'] + 
                       '_' + full_combo['confirmation_type'])

# Filter for combinations with at least 3 trades
full_combo_filtered = full_combo[full_combo['trades'] >= 3].copy()
full_combo_filtered = full_combo_filtered.sort_values('net_pnl', ascending=False)

print("\nTop 30 Most Profitable Symbol+Strategy Combinations (min 3 trades):")
print("-"*100)
print(f"{'Symbol':<12} {'Strategy+Range+Conf':<20} {'Trades':>7} {'Win Rate':>9} {'Net P/L':>12} {'Avg':>10}")
print("-"*100)

for _, row in full_combo_filtered.head(30).iterrows():
    print(f"{row['symbol']:<12} {row['combo']:<20} {int(row['trades']):>7} "
          f"{row['win_rate']:>8.1f}% ${row['net_pnl']:>11.2f} ${row['avg_profit']:>9.2f}")

print("\n\nBottom 30 Worst Performing Symbol+Strategy Combinations (min 3 trades):")
print("-"*100)
print(f"{'Symbol':<12} {'Strategy+Range+Conf':<20} {'Trades':>7} {'Win Rate':>9} {'Net P/L':>12} {'Avg':>10}")
print("-"*100)

for _, row in full_combo_filtered.tail(30).iterrows():
    print(f"{row['symbol']:<12} {row['combo']:<20} {int(row['trades']):>7} "
          f"{row['win_rate']:>8.1f}% ${row['net_pnl']:>11.2f} ${row['avg_profit']:>9.2f}")

print("\n" + "="*100)
print("ANALYSIS COMPLETE")
print("="*100)

