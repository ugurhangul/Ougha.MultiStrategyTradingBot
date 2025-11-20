"""
Analyze backtest results to find best and worst symbol/strategy pairs.

This script:
1. Loads trade data from SimulatedBroker's closed_trades (via pickle or direct access)
2. Parses comment field to extract strategy information
3. Calculates performance metrics for each symbol/strategy pair
4. Ranks pairs from best to worst
5. Generates detailed reports
"""
import re
import json
import pickle
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from datetime import datetime
import pandas as pd
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.comment_parser import CommentParser

# Rich console formatting (optional, with fallback to plain text)
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None


class BacktestResultsAnalyzer:
    """Analyze backtest results from SimulatedBroker trade data."""

    def __init__(self, trades_data: Optional[List[Dict]] = None):
        """
        Initialize analyzer.

        Args:
            trades_data: List of trade dictionaries from SimulatedBroker.get_closed_trades()
                        If None, will attempt to load from pickle file
        """
        self.trades_data = trades_data or []
        self.trades: List[Dict] = []
        self.symbol_strategy_stats: Dict = defaultdict(lambda: {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_profit': 0.0,
            'gross_profit': 0.0,
            'gross_loss': 0.0,
            'trades': []
        })
    
    def parse_trades(self):
        """Parse trade data from SimulatedBroker's closed_trades."""
        print("Parsing backtest trade data...")

        if not self.trades_data:
            print("  ✗ No trade data provided")
            return

        total_trades = 0
        skipped_trades = 0

        for trade in self.trades_data:
            ticket = trade.get('ticket')
            symbol = trade.get('symbol')
            trade_type = trade.get('type')
            profit = trade.get('profit', 0.0)
            comment = trade.get('comment', '')
            open_time = trade.get('open_time')
            close_time = trade.get('close_time')

            # Parse comment to extract strategy information
            parsed = CommentParser.parse(comment)

            if parsed:
                # Extract strategy type and range_id
                strategy_type = parsed.strategy_type  # "TB", "FB", or "HFT"
                range_id = parsed.range_id  # "15M_1M", "4H_5M", etc.

                # Create strategy key
                if range_id:
                    strategy_key = f"{strategy_type}_{range_id}"
                else:
                    strategy_key = strategy_type
            else:
                # Fallback: try to extract from comment directly
                if '|' in comment:
                    parts = comment.split('|')
                    if len(parts) >= 2:
                        strategy_key = f"{parts[0]}_{parts[1]}" if len(parts) > 2 else parts[0]
                    else:
                        strategy_key = "UNKNOWN"
                        skipped_trades += 1
                else:
                    strategy_key = "UNKNOWN"
                    skipped_trades += 1

            # Create trade record
            trade_record = {
                'ticket': ticket,
                'symbol': symbol,
                'type': trade_type,
                'profit': profit,
                'strategy': strategy_key,
                'comment': comment,
                'open_time': open_time,
                'close_time': close_time
            }

            self.trades.append(trade_record)
            total_trades += 1

            # Update symbol/strategy stats
            pair_key = f"{symbol}_{strategy_key}"
            stats = self.symbol_strategy_stats[pair_key]
            stats['total_trades'] += 1
            stats['total_profit'] += profit
            stats['trades'].append(trade_record)

            if profit > 0:
                stats['winning_trades'] += 1
                stats['gross_profit'] += profit
            elif profit < 0:
                stats['losing_trades'] += 1
                stats['gross_loss'] += abs(profit)

        print(f"  ✓ Processed {total_trades} trades")
        if skipped_trades > 0:
            print(f"  ⚠ Skipped {skipped_trades} trades with unparseable comments")
        print(f"  ✓ Found {len(self.symbol_strategy_stats)} unique symbol/strategy pairs")
        print()
    
    def calculate_metrics(self):
        """Calculate performance metrics for each symbol/strategy pair."""
        print("Calculating performance metrics...")
        
        for pair_key, stats in self.symbol_strategy_stats.items():
            total_trades = stats['total_trades']
            
            if total_trades == 0:
                continue
            
            # Calculate metrics
            stats['win_rate'] = (stats['winning_trades'] / total_trades * 100) if total_trades > 0 else 0
            stats['avg_profit'] = stats['total_profit'] / total_trades
            stats['profit_factor'] = (stats['gross_profit'] / stats['gross_loss']) if stats['gross_loss'] > 0 else float('inf')
            
            # Calculate expectancy (average profit per trade)
            stats['expectancy'] = stats['avg_profit']
        
        print(f"  ✓ Calculated metrics for {len(self.symbol_strategy_stats)} pairs")
        print()

    def get_ranked_pairs(self, sort_by: str = 'total_profit') -> List[Tuple[str, Dict]]:
        """
        Get symbol/strategy pairs ranked by performance.

        Args:
            sort_by: Metric to sort by ('total_profit', 'win_rate', 'profit_factor', 'expectancy')

        Returns:
            List of (pair_key, stats) tuples sorted by metric
        """
        pairs = list(self.symbol_strategy_stats.items())

        # Sort by the specified metric (descending)
        pairs.sort(key=lambda x: x[1].get(sort_by, 0), reverse=True)

        return pairs

    def print_top_pairs(self, n: int = 20, sort_by: str = 'total_profit'):
        """Print top N best performing pairs."""
        print(f"\n{'='*120}")
        print(f"TOP {n} BEST PERFORMING SYMBOL/STRATEGY PAIRS (sorted by {sort_by})")
        print(f"{'='*120}")
        print(f"{'Rank':<6} {'Symbol/Strategy':<30} {'Trades':<8} {'Win%':<8} {'Profit':<12} {'PF':<8} {'Avg/Trade':<12}")
        print(f"{'-'*120}")

        ranked = self.get_ranked_pairs(sort_by)

        for i, (pair_key, stats) in enumerate(ranked[:n], 1):
            pf_display = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "∞"

            print(f"{i:<6} {pair_key:<30} {stats['total_trades']:<8} "
                  f"{stats['win_rate']:<8.2f} ${stats['total_profit']:<11.2f} "
                  f"{pf_display:<8} ${stats['avg_profit']:<11.2f}")

        print()

    def print_bottom_pairs(self, n: int = 20, sort_by: str = 'total_profit'):
        """Print bottom N worst performing pairs."""
        print(f"\n{'='*120}")
        print(f"TOP {n} WORST PERFORMING SYMBOL/STRATEGY PAIRS (sorted by {sort_by})")
        print(f"{'='*120}")
        print(f"{'Rank':<6} {'Symbol/Strategy':<30} {'Trades':<8} {'Win%':<8} {'Profit':<12} {'PF':<8} {'Avg/Trade':<12}")
        print(f"{'-'*120}")

        ranked = self.get_ranked_pairs(sort_by)

        # Get bottom N (reverse order)
        for i, (pair_key, stats) in enumerate(reversed(ranked[-n:]), 1):
            pf_display = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "∞"

            print(f"{i:<6} {pair_key:<30} {stats['total_trades']:<8} "
                  f"{stats['win_rate']:<8.2f} ${stats['total_profit']:<11.2f} "
                  f"{pf_display:<8} ${stats['avg_profit']:<11.2f}")

        print()

    def print_summary_by_symbol(self):
        """Print summary statistics grouped by symbol."""
        # Aggregate by symbol
        symbol_stats = defaultdict(lambda: {
            'total_trades': 0,
            'winning_trades': 0,
            'total_profit': 0.0,
            'gross_profit': 0.0,
            'gross_loss': 0.0
        })

        for pair_key, stats in self.symbol_strategy_stats.items():
            # Extract symbol from "SYMBOL_STRATEGY"
            # Symbol is everything before the strategy pattern (TB_*, FB_*, HFT_*)
            import re
            strategy_match = re.search(r'_(TB|FB|HFT)_', pair_key)
            if strategy_match:
                # Symbol is everything before the strategy pattern
                symbol = pair_key[:strategy_match.start()]
            else:
                # Fallback: take first part before underscore
                symbol = pair_key.split('_')[0]

            symbol_stats[symbol]['total_trades'] += stats['total_trades']
            symbol_stats[symbol]['winning_trades'] += stats['winning_trades']
            symbol_stats[symbol]['total_profit'] += stats['total_profit']
            symbol_stats[symbol]['gross_profit'] += stats['gross_profit']
            symbol_stats[symbol]['gross_loss'] += stats['gross_loss']

        # Calculate metrics and sort
        symbol_list = []
        for symbol, stats in symbol_stats.items():
            stats['win_rate'] = (stats['winning_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
            stats['profit_factor'] = (stats['gross_profit'] / stats['gross_loss']) if stats['gross_loss'] > 0 else float('inf')
            stats['avg_profit'] = stats['total_profit'] / stats['total_trades'] if stats['total_trades'] > 0 else 0
            symbol_list.append((symbol, stats))

        # Sort by total profit
        symbol_list.sort(key=lambda x: x[1]['total_profit'], reverse=True)

        if RICH_AVAILABLE:
            # Rich formatted table
            table = Table(title="📈 Performance by Symbol (All Strategies Combined)", show_header=True, header_style="bold cyan")
            table.add_column("Symbol", style="cyan", width=12)
            table.add_column("Trades", justify="right", width=8)
            table.add_column("Win%", justify="right", width=8)
            table.add_column("Profit", justify="right", width=12)
            table.add_column("PF", justify="right", width=8)
            table.add_column("Avg/Trade", justify="right", width=12)

            for symbol, stats in symbol_list:
                pf_display = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "∞"
                profit = stats['total_profit']
                profit_color = "green" if profit > 0 else "red"
                win_rate = stats['win_rate']
                wr_color = "green" if win_rate > 60 else "yellow" if win_rate > 50 else "white"

                table.add_row(
                    symbol,
                    str(stats['total_trades']),
                    f"[{wr_color}]{win_rate:.2f}%[/{wr_color}]",
                    f"[{profit_color}]${profit:,.2f}[/{profit_color}]",
                    pf_display,
                    f"${stats['avg_profit']:,.2f}"
                )

            console.print()
            console.print(table)
            console.print()
        else:
            # Plain text fallback
            print(f"\n{'='*120}")
            print(f"PERFORMANCE BY SYMBOL (All Strategies Combined)")
            print(f"{'='*120}")
            print(f"{'Symbol':<12} {'Trades':<8} {'Win%':<8} {'Profit':<12} {'PF':<8} {'Avg/Trade':<12}")
            print(f"{'-'*120}")

            for symbol, stats in symbol_list:
                pf_display = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "∞"
                print(f"{symbol:<12} {stats['total_trades']:<8} "
                      f"{stats['win_rate']:<8.2f} ${stats['total_profit']:<11.2f} "
                      f"{pf_display:<8} ${stats['avg_profit']:<11.2f}")

            print()

    def print_summary_by_strategy(self):
        """Print summary statistics grouped by strategy."""
        # Aggregate by strategy
        strategy_stats = defaultdict(lambda: {
            'total_trades': 0,
            'winning_trades': 0,
            'total_profit': 0.0,
            'gross_profit': 0.0,
            'gross_loss': 0.0
        })

        for pair_key, stats in self.symbol_strategy_stats.items():
            # Extract strategy from "SYMBOL_STRATEGY"
            # Strategy is the part that matches TB_* or FB_* or HFT_*
            # This handles symbols like "US30_x10_TB_4H_5M" correctly

            # Find the strategy pattern (TB, FB, or HFT followed by timeframes)
            import re
            strategy_match = re.search(r'(TB|FB|HFT)_(\w+_\w+)', pair_key)
            if strategy_match:
                strategy = strategy_match.group(0)  # e.g., "TB_4H_5M"
            else:
                # Fallback: everything after first underscore
                parts = pair_key.split('_', 1)
                strategy = parts[1] if len(parts) > 1 else "UNKNOWN"

            strategy_stats[strategy]['total_trades'] += stats['total_trades']
            strategy_stats[strategy]['winning_trades'] += stats['winning_trades']
            strategy_stats[strategy]['total_profit'] += stats['total_profit']
            strategy_stats[strategy]['gross_profit'] += stats['gross_profit']
            strategy_stats[strategy]['gross_loss'] += stats['gross_loss']

        # Calculate metrics and sort
        strategy_list = []
        for strategy, stats in strategy_stats.items():
            stats['win_rate'] = (stats['winning_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
            stats['profit_factor'] = (stats['gross_profit'] / stats['gross_loss']) if stats['gross_loss'] > 0 else float('inf')
            stats['avg_profit'] = stats['total_profit'] / stats['total_trades'] if stats['total_trades'] > 0 else 0
            strategy_list.append((strategy, stats))

        # Sort by total profit
        strategy_list.sort(key=lambda x: x[1]['total_profit'], reverse=True)

        if RICH_AVAILABLE:
            # Rich formatted table
            table = Table(title="🎯 Performance by Strategy (All Symbols Combined)", show_header=True, header_style="bold cyan")
            table.add_column("Strategy", style="cyan", width=20)
            table.add_column("Trades", justify="right", width=8)
            table.add_column("Win%", justify="right", width=8)
            table.add_column("Profit", justify="right", width=12)
            table.add_column("PF", justify="right", width=8)
            table.add_column("Avg/Trade", justify="right", width=12)

            for strategy, stats in strategy_list:
                pf_display = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "∞"
                profit = stats['total_profit']
                profit_color = "green" if profit > 0 else "red"
                win_rate = stats['win_rate']
                wr_color = "green" if win_rate > 60 else "yellow" if win_rate > 50 else "white"

                table.add_row(
                    strategy,
                    str(stats['total_trades']),
                    f"[{wr_color}]{win_rate:.2f}%[/{wr_color}]",
                    f"[{profit_color}]${profit:,.2f}[/{profit_color}]",
                    pf_display,
                    f"${stats['avg_profit']:,.2f}"
                )

            console.print()
            console.print(table)
            console.print()
        else:
            # Plain text fallback
            print(f"\n{'='*120}")
            print(f"PERFORMANCE BY STRATEGY (All Symbols Combined)")
            print(f"{'='*120}")
            print(f"{'Strategy':<20} {'Trades':<8} {'Win%':<8} {'Profit':<12} {'PF':<8} {'Avg/Trade':<12}")
            print(f"{'-'*120}")

            for strategy, stats in strategy_list:
                pf_display = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "∞"
                print(f"{strategy:<20} {stats['total_trades']:<8} "
                      f"{stats['win_rate']:<8.2f} ${stats['total_profit']:<11.2f} "
                      f"{pf_display:<8} ${stats['avg_profit']:<11.2f}")

            print()

    def export_to_csv(self, output_file: str = "backtest_analysis.csv"):
        """Export detailed analysis to CSV file."""
        print(f"Exporting results to {output_file}...")

        # Prepare data for export
        rows = []
        for pair_key, stats in self.symbol_strategy_stats.items():
            # Extract symbol and strategy properly
            import re

            # Find strategy pattern
            strategy_match = re.search(r'(TB|FB|HFT)_(\w+_\w+)', pair_key)
            if strategy_match:
                strategy = strategy_match.group(0)  # e.g., "TB_4H_5M"
                # Symbol is everything before the strategy
                symbol_match = re.search(r'_(TB|FB|HFT)_', pair_key)
                symbol = pair_key[:symbol_match.start()] if symbol_match else pair_key.split('_')[0]
            else:
                # Fallback
                parts = pair_key.split('_', 1)
                symbol = parts[0]
                strategy = parts[1] if len(parts) > 1 else "UNKNOWN"

            pf = stats['profit_factor'] if stats['profit_factor'] != float('inf') else 999.99

            rows.append({
                'Symbol': symbol,
                'Strategy': strategy,
                'Pair': pair_key,
                'Total_Trades': stats['total_trades'],
                'Winning_Trades': stats['winning_trades'],
                'Losing_Trades': stats['losing_trades'],
                'Win_Rate_%': stats['win_rate'],
                'Total_Profit_$': stats['total_profit'],
                'Gross_Profit_$': stats['gross_profit'],
                'Gross_Loss_$': stats['gross_loss'],
                'Profit_Factor': pf,
                'Avg_Profit_Per_Trade_$': stats['avg_profit'],
                'Expectancy_$': stats['expectancy']
            })

        # Create DataFrame and sort by total profit
        df = pd.DataFrame(rows)
        df = df.sort_values('Total_Profit_$', ascending=False)

        # Export to CSV
        df.to_csv(output_file, index=False)
        print(f"  ✓ Exported {len(rows)} symbol/strategy pairs to {output_file}")
        print()

    def export_trades_to_csv(self, output_file: str = "backtest_trades.csv"):
        """Export all individual trades to CSV file."""
        print(f"Exporting trades to {output_file}...")

        # Create DataFrame from trades
        df = pd.DataFrame(self.trades)

        # Sort by close_time if available, otherwise by ticket
        if 'close_time' in df.columns:
            df = df.sort_values(['close_time', 'ticket'])
        elif 'ticket' in df.columns:
            df = df.sort_values('ticket')

        # Export to CSV
        df.to_csv(output_file, index=False)
        print(f"  ✓ Exported {len(self.trades)} trades to {output_file}")
        print()


def load_trades_from_pickle(pickle_file: str = "backtest_trades.pkl") -> Optional[List[Dict]]:
    """
    Load trades from pickle file.

    Args:
        pickle_file: Path to pickle file

    Returns:
        List of trade dictionaries or None if file not found
    """
    pickle_path = Path(pickle_file)
    if pickle_path.exists():
        with open(pickle_path, 'rb') as f:
            return pickle.load(f)
    return None


def main():
    """Main entry point."""
    print("\n" + "="*120)
    print("BACKTEST RESULTS ANALYZER")
    print("="*120)
    print()

    # Try to load trades from pickle file first
    print("Looking for trade data...")
    trades_data = load_trades_from_pickle("backtest_trades.pkl")

    if not trades_data:
        print("  ✗ No pickle file found (backtest_trades.pkl)")
        print()
        print("To use this analyzer:")
        print("  1. Modify backtest.py to save trades using:")
        print("     import pickle")
        print("     trades = backtest_controller.broker.get_closed_trades()")
        print("     with open('backtest_trades.pkl', 'wb') as f:")
        print("         pickle.dump(trades, f)")
        print()
        print("  2. Or pass trades_data directly to BacktestResultsAnalyzer()")
        print()
        return

    print(f"  ✓ Loaded {len(trades_data)} trades from pickle file")
    print()

    # Create analyzer with trade data
    analyzer = BacktestResultsAnalyzer(trades_data=trades_data)

    # Parse trades
    analyzer.parse_trades()

    # Calculate metrics
    analyzer.calculate_metrics()

    # Print summaries
    analyzer.print_summary_by_symbol()
    analyzer.print_summary_by_strategy()

    # Print top and bottom pairs
    analyzer.print_top_pairs(n=30, sort_by='total_profit')
    analyzer.print_bottom_pairs(n=30, sort_by='total_profit')

    # Also show by win rate
    analyzer.print_top_pairs(n=20, sort_by='win_rate')

    # Also show by profit factor
    analyzer.print_top_pairs(n=20, sort_by='profit_factor')

    # Export to CSV
    analyzer.export_to_csv("backtest_analysis.csv")
    analyzer.export_trades_to_csv("backtest_trades.csv")

    print("\n" + "="*120)
    print("ANALYSIS COMPLETE")
    print("="*120)
    print()
    print("Files generated:")
    print("  - backtest_analysis.csv  (Symbol/strategy pair statistics)")
    print("  - backtest_trades.csv    (Individual trade records)")
    print()


if __name__ == "__main__":
    main()

