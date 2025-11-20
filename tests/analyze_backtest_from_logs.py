"""
Quick analysis tool that parses main.log to extract trade data.

This is a temporary solution until backtest_trades.pkl is generated.
For accurate analysis, run the backtest again to generate the pickle file.
"""
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from analyze_backtest_results import BacktestResultsAnalyzer


def parse_main_log(log_file: str = "logs/backtest/2025-11-14/main.log"):
    """
    Parse main.log file to extract trade data.
    
    Returns:
        List of trade dictionaries
    """
    print(f"Parsing {log_file}...")
    
    trades = []
    
    # Pattern to match position closed lines
    close_pattern = re.compile(
        r'\[BACKTEST\] Position (\d+) closed: (\w+) (BUY|SELL) \| Profit: \$([+-]?\d+\.\d+)'
    )
    
    # Pattern to match position closed with strategy info (appears a few lines later)
    # Example: Position 7593 closed: BTCAUD | Profit: $-287.03 | Volume: 0.50
    # Followed by: [BTCAUD] [TB|15M_1M] Position closed: LOSS $-287.03
    strategy_pattern = re.compile(
        r'\[(\w+)\] \[([^\]]+)\] Position closed:'
    )
    
    # Read file and build ticket -> strategy mapping
    ticket_to_strategy = {}
    
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # First pass: build ticket -> strategy mapping
    for i, line in enumerate(lines):
        match = strategy_pattern.search(line)
        if match:
            symbol = match.group(1)
            strategy_info = match.group(2)  # e.g., "TB|15M_1M" or "FB|4H_5M"
            
            # Look backwards for the position closed line
            for j in range(max(0, i-10), i):
                close_match = close_pattern.search(lines[j])
                if close_match and close_match.group(2) == symbol:
                    ticket = int(close_match.group(1))
                    ticket_to_strategy[ticket] = strategy_info
                    break
    
    # Second pass: extract all trades
    for line in lines:
        match = close_pattern.search(line)
        if match:
            ticket = int(match.group(1))
            symbol = match.group(2)
            trade_type = match.group(3)
            profit = float(match.group(4))
            
            # Get strategy from mapping
            strategy_info = ticket_to_strategy.get(ticket, "UNKNOWN")
            
            # Parse strategy info (e.g., "TB|15M_1M" -> "TB_15M_1M")
            if '|' in strategy_info:
                parts = strategy_info.split('|')
                if len(parts) >= 2:
                    comment = strategy_info  # Keep original format for comment
                else:
                    comment = strategy_info
            else:
                comment = strategy_info
            
            trade = {
                'ticket': ticket,
                'symbol': symbol,
                'type': trade_type,
                'profit': profit,
                'comment': comment,
                'open_time': None,
                'close_time': None
            }
            
            trades.append(trade)
    
    print(f"  ✓ Extracted {len(trades)} trades")
    print(f"  ✓ Mapped {len(ticket_to_strategy)} trades to strategies")
    print()
    
    return trades


def main():
    """Main entry point."""
    print("\n" + "="*120)
    print("BACKTEST RESULTS ANALYZER (from logs)")
    print("="*120)
    print()
    print("NOTE: This parses logs which may be incomplete.")
    print("For accurate analysis, run backtest again to generate backtest_trades.pkl")
    print()
    
    # Parse main.log
    trades_data = parse_main_log()
    
    if not trades_data:
        print("No trades found in logs")
        return
    
    # Create analyzer
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
    
    # Export to CSV
    analyzer.export_to_csv("backtest_analysis.csv")
    analyzer.export_trades_to_csv("backtest_trades.csv")
    
    print("\n" + "="*120)
    print("ANALYSIS COMPLETE")
    print("="*120)
    print()


if __name__ == "__main__":
    main()

