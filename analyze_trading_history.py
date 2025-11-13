#!/usr/bin/env python3
"""
MT5 Trading History Analysis Tool

This standalone script connects to MetaTrader 5 and performs comprehensive analysis
of historical trading data, including:
- Overall performance metrics
- Risk metrics (drawdown, Sharpe ratio, etc.)
- Strategy-specific statistics (TB vs FB)
- Time-based analysis
- Confirmation analysis
- Symbol distribution

Usage:
    python analyze_trading_history.py [--days DAYS] [--output OUTPUT] [--format FORMAT]

Arguments:
    --days DAYS         Number of days to look back (default: all available)
    --output OUTPUT     Output file path (optional, default: console only)
    --format FORMAT     Output format: console, csv, both (default: console)
    --symbols SYMBOLS   Comma-separated list of symbols to analyze (default: all)
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import csv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

from src.config import TradingConfig
from src.core.mt5_connector import MT5Connector
from src.utils.logger import init_logger
from src.utils.comment_parser import CommentParser
import MetaTrader5 as mt5


class TradingAnalyzer:
    """Comprehensive trading history analyzer"""
    
    def __init__(self, connector: MT5Connector, magic_number: int):
        """
        Initialize the analyzer.
        
        Args:
            connector: MT5 connector instance
            magic_number: Magic number to filter trades
        """
        self.connector = connector
        self.magic_number = magic_number
        self.logger = init_logger(log_to_file=False, log_to_console=True, log_level="INFO", enable_detailed=False)
        
    def fetch_trade_history(self, days_back: Optional[int] = None, symbols: Optional[List[str]] = None) -> List[Dict]:
        """
        Fetch complete trading history from MT5.
        
        Args:
            days_back: Number of days to look back (None = all available)
            symbols: List of symbols to filter (None = all symbols)
            
        Returns:
            List of trade dictionaries with all relevant information
        """
        if not self.connector.is_connected:
            self.logger.error("MT5 not connected")
            return []
        
        try:
            # Calculate date range
            to_date = datetime.now()
            if days_back:
                from_date = to_date - timedelta(days=days_back)
            else:
                # Get all available history (go back 10 years)
                from_date = to_date - timedelta(days=3650)
            
            self.logger.info(f"Fetching trade history from {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}")
            
            # Get all deals in the date range
            deals = mt5.history_deals_get(from_date, to_date)
            
            if deals is None or len(deals) == 0:
                self.logger.warning("No history deals found")
                return []
            
            self.logger.info(f"Retrieved {len(deals)} deals from MT5")
            
            # Group deals by position_id to match IN and OUT deals
            position_deals = defaultdict(list)
            for deal in deals:
                # Filter by magic number
                if deal.magic != self.magic_number:
                    continue
                
                # Filter by symbols if specified
                if symbols and deal.symbol not in symbols:
                    continue
                
                position_deals[deal.position_id].append(deal)
            
            # Process closed positions (those with both IN and OUT deals)
            trades = []
            for position_id, deals_list in position_deals.items():
                # Find IN and OUT deals
                in_deal = None
                out_deal = None
                
                for deal in deals_list:
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        in_deal = deal
                    elif deal.entry == mt5.DEAL_ENTRY_OUT:
                        out_deal = deal
                
                # Only process if we have both IN and OUT (closed position)
                if in_deal and out_deal:
                    # Parse comment to extract strategy info from ENTRY_IN deal
                    # MT5 overwrites the comment on ENTRY_OUT with [sl X.XXX] or [tp X.XXX]
                    # The original strategy comment is preserved in the ENTRY_IN deal
                    parsed_comment = CommentParser.parse(in_deal.comment)

                    trade_info = {
                        'position_id': position_id,
                        'symbol': out_deal.symbol,
                        'entry_time': datetime.fromtimestamp(in_deal.time),
                        'exit_time': datetime.fromtimestamp(out_deal.time),
                        'entry_price': in_deal.price,
                        'exit_price': out_deal.price,
                        'volume': out_deal.volume,
                        'profit': out_deal.profit,
                        'commission': in_deal.commission + out_deal.commission,
                        'swap': in_deal.swap + out_deal.swap,
                        'comment': in_deal.comment,  # Use ENTRY_IN comment (has strategy info)
                        'direction': 'BUY' if in_deal.type == mt5.ORDER_TYPE_BUY else 'SELL',
                        'duration_minutes': (datetime.fromtimestamp(out_deal.time) - datetime.fromtimestamp(in_deal.time)).total_seconds() / 60,
                    }
                    
                    # Add parsed comment info if available
                    if parsed_comment:
                        trade_info['strategy_type'] = parsed_comment.strategy_type
                        trade_info['range_id'] = parsed_comment.range_id
                        trade_info['has_volume_confirmation'] = parsed_comment.has_volume_confirmation
                        trade_info['has_divergence_confirmation'] = parsed_comment.has_divergence_confirmation
                    else:
                        trade_info['strategy_type'] = 'UNKNOWN'
                        trade_info['range_id'] = 'UNKNOWN'
                        trade_info['has_volume_confirmation'] = False
                        trade_info['has_divergence_confirmation'] = False
                    
                    trades.append(trade_info)
            
            self.logger.info(f"Processed {len(trades)} closed positions")
            return sorted(trades, key=lambda x: x['entry_time'])
            
        except Exception as e:
            self.logger.error(f"Error fetching trade history: {e}")
            return []

    def calculate_statistics(self, trades: List[Dict]) -> Dict:
        """
        Calculate comprehensive trading statistics.

        Args:
            trades: List of trade dictionaries

        Returns:
            Dictionary containing all calculated statistics
        """
        if not trades:
            return {}

        stats = {
            'overall': self._calculate_overall_stats(trades),
            'risk_metrics': self._calculate_risk_metrics(trades),
            'by_symbol': self._calculate_by_symbol(trades),
            'by_strategy': self._calculate_by_strategy(trades),
            'by_range': self._calculate_by_range(trades),
            'by_confirmation': self._calculate_by_confirmation(trades),
            'by_time': self._calculate_time_based(trades),
        }

        return stats

    def _calculate_overall_stats(self, trades: List[Dict]) -> Dict:
        """Calculate overall performance metrics"""
        total_trades = len(trades)
        winning_trades = [t for t in trades if t['profit'] > 0]
        losing_trades = [t for t in trades if t['profit'] <= 0]

        total_profit = sum(t['profit'] for t in winning_trades)
        total_loss = abs(sum(t['profit'] for t in losing_trades))
        net_profit = sum(t['profit'] for t in trades)

        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0

        avg_win = total_profit / len(winning_trades) if winning_trades else 0
        avg_loss = total_loss / len(losing_trades) if losing_trades else 0

        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        avg_duration = sum(t['duration_minutes'] for t in trades) / total_trades if total_trades > 0 else 0

        # Calculate largest win/loss
        largest_win = max((t['profit'] for t in trades), default=0)
        largest_loss = min((t['profit'] for t in trades), default=0)

        # Calculate consecutive wins/losses
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_consecutive_wins = 0
        current_consecutive_losses = 0

        for trade in trades:
            if trade['profit'] > 0:
                current_consecutive_wins += 1
                current_consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_consecutive_wins)
            else:
                current_consecutive_losses += 1
                current_consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)

        return {
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'net_profit': net_profit,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'avg_duration_minutes': avg_duration,
            'largest_win': largest_win,
            'largest_loss': largest_loss,
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses,
        }

    def _calculate_risk_metrics(self, trades: List[Dict]) -> Dict:
        """Calculate risk-related metrics"""
        if not trades:
            return {}

        # Calculate equity curve
        equity_curve = []
        running_equity = 0
        peak_equity = 0
        max_drawdown = 0
        current_drawdown = 0

        for trade in trades:
            running_equity += trade['profit']
            equity_curve.append(running_equity)

            if running_equity > peak_equity:
                peak_equity = running_equity
                current_drawdown = 0
            else:
                current_drawdown = peak_equity - running_equity
                max_drawdown = max(max_drawdown, current_drawdown)

        max_drawdown_percent = (max_drawdown / peak_equity * 100) if peak_equity > 0 else 0

        # Calculate Sharpe ratio (simplified - assumes risk-free rate of 0)
        returns = [t['profit'] for t in trades]
        avg_return = sum(returns) / len(returns) if returns else 0

        if len(returns) > 1:
            variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
            std_dev = variance ** 0.5
            sharpe_ratio = (avg_return / std_dev) if std_dev > 0 else 0
        else:
            sharpe_ratio = 0

        # Calculate average risk-reward ratio
        rr_ratios = []
        for trade in trades:
            if trade['profit'] > 0:
                # For winning trades, we can estimate RR from the profit
                # This is approximate since we don't have the original SL/TP
                rr_ratios.append(abs(trade['profit']))

        avg_rr = sum(rr_ratios) / len(rr_ratios) if rr_ratios else 0

        return {
            'max_drawdown': max_drawdown,
            'max_drawdown_percent': max_drawdown_percent,
            'sharpe_ratio': sharpe_ratio,
            'final_equity': running_equity,
            'peak_equity': peak_equity,
        }

    def _calculate_by_symbol(self, trades: List[Dict]) -> Dict:
        """Calculate statistics per symbol"""
        symbol_stats = defaultdict(lambda: {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0})

        for trade in trades:
            symbol = trade['symbol']
            symbol_stats[symbol]['trades'].append(trade)
            symbol_stats[symbol]['profit'] += trade['profit']
            if trade['profit'] > 0:
                symbol_stats[symbol]['wins'] += 1
            else:
                symbol_stats[symbol]['losses'] += 1

        # Calculate win rate and other metrics for each symbol
        result = {}
        for symbol, data in symbol_stats.items():
            total = len(data['trades'])
            result[symbol] = {
                'total_trades': total,
                'winning_trades': data['wins'],
                'losing_trades': data['losses'],
                'win_rate': (data['wins'] / total * 100) if total > 0 else 0,
                'net_profit': data['profit'],
            }

        return result

    def _calculate_by_strategy(self, trades: List[Dict]) -> Dict:
        """Calculate statistics per strategy type (TB vs FB)"""
        strategy_stats = defaultdict(lambda: {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0})

        for trade in trades:
            strategy = trade['strategy_type']
            strategy_stats[strategy]['trades'].append(trade)
            strategy_stats[strategy]['profit'] += trade['profit']
            if trade['profit'] > 0:
                strategy_stats[strategy]['wins'] += 1
            else:
                strategy_stats[strategy]['losses'] += 1

        result = {}
        for strategy, data in strategy_stats.items():
            total = len(data['trades'])
            result[strategy] = {
                'total_trades': total,
                'winning_trades': data['wins'],
                'losing_trades': data['losses'],
                'win_rate': (data['wins'] / total * 100) if total > 0 else 0,
                'net_profit': data['profit'],
            }

        return result

    def _calculate_by_range(self, trades: List[Dict]) -> Dict:
        """Calculate statistics per range configuration"""
        range_stats = defaultdict(lambda: {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0})

        for trade in trades:
            range_id = trade['range_id']
            range_stats[range_id]['trades'].append(trade)
            range_stats[range_id]['profit'] += trade['profit']
            if trade['profit'] > 0:
                range_stats[range_id]['wins'] += 1
            else:
                range_stats[range_id]['losses'] += 1

        result = {}
        for range_id, data in range_stats.items():
            total = len(data['trades'])
            result[range_id] = {
                'total_trades': total,
                'winning_trades': data['wins'],
                'losing_trades': data['losses'],
                'win_rate': (data['wins'] / total * 100) if total > 0 else 0,
                'net_profit': data['profit'],
            }

        return result

    def _calculate_by_confirmation(self, trades: List[Dict]) -> Dict:
        """Calculate statistics based on confirmation types"""
        confirmation_stats = {
            'volume_only': {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0},
            'divergence_only': {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0},
            'both_confirmations': {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0},
            'no_confirmations': {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0},
        }

        for trade in trades:
            has_vol = trade['has_volume_confirmation']
            has_div = trade['has_divergence_confirmation']

            if has_vol and has_div:
                key = 'both_confirmations'
            elif has_vol:
                key = 'volume_only'
            elif has_div:
                key = 'divergence_only'
            else:
                key = 'no_confirmations'

            confirmation_stats[key]['trades'].append(trade)
            confirmation_stats[key]['profit'] += trade['profit']
            if trade['profit'] > 0:
                confirmation_stats[key]['wins'] += 1
            else:
                confirmation_stats[key]['losses'] += 1

        result = {}
        for conf_type, data in confirmation_stats.items():
            total = len(data['trades'])
            if total > 0:
                result[conf_type] = {
                    'total_trades': total,
                    'winning_trades': data['wins'],
                    'losing_trades': data['losses'],
                    'win_rate': (data['wins'] / total * 100) if total > 0 else 0,
                    'net_profit': data['profit'],
                }

        return result

    def _calculate_time_based(self, trades: List[Dict]) -> Dict:
        """Calculate time-based statistics"""
        # By day of week
        day_stats = defaultdict(lambda: {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0})
        # By hour of day
        hour_stats = defaultdict(lambda: {'trades': [], 'profit': 0, 'wins': 0, 'losses': 0})

        for trade in trades:
            # Day of week (0=Monday, 6=Sunday)
            day = trade['entry_time'].weekday()
            day_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][day]
            day_stats[day_name]['trades'].append(trade)
            day_stats[day_name]['profit'] += trade['profit']
            if trade['profit'] > 0:
                day_stats[day_name]['wins'] += 1
            else:
                day_stats[day_name]['losses'] += 1

            # Hour of day
            hour = trade['entry_time'].hour
            hour_stats[hour]['trades'].append(trade)
            hour_stats[hour]['profit'] += trade['profit']
            if trade['profit'] > 0:
                hour_stats[hour]['wins'] += 1
            else:
                hour_stats[hour]['losses'] += 1

        # Format results
        by_day = {}
        for day, data in day_stats.items():
            total = len(data['trades'])
            by_day[day] = {
                'total_trades': total,
                'win_rate': (data['wins'] / total * 100) if total > 0 else 0,
                'net_profit': data['profit'],
            }

        by_hour = {}
        for hour, data in hour_stats.items():
            total = len(data['trades'])
            by_hour[hour] = {
                'total_trades': total,
                'win_rate': (data['wins'] / total * 100) if total > 0 else 0,
                'net_profit': data['profit'],
            }

        return {
            'by_day_of_week': by_day,
            'by_hour_of_day': by_hour,
        }

    def print_statistics(self, stats: Dict):
        """Print statistics to console in a readable format"""
        if not stats:
            print("\nNo statistics to display")
            return

        print("\n" + "="*80)
        print("TRADING HISTORY ANALYSIS")
        print("="*80)

        # Overall Performance
        if 'overall' in stats:
            overall = stats['overall']
            print("\n" + "-"*80)
            print("OVERALL PERFORMANCE")
            print("-"*80)
            print(f"Total Trades:           {overall['total_trades']}")
            print(f"Winning Trades:         {overall['winning_trades']}")
            print(f"Losing Trades:          {overall['losing_trades']}")
            print(f"Win Rate:               {overall['win_rate']:.2f}%")
            print(f"Total Profit:           ${overall['total_profit']:.2f}")
            print(f"Total Loss:             ${overall['total_loss']:.2f}")
            print(f"Net Profit:             ${overall['net_profit']:.2f}")
            print(f"Average Win:            ${overall['avg_win']:.2f}")
            print(f"Average Loss:           ${overall['avg_loss']:.2f}")
            print(f"Profit Factor:          {overall['profit_factor']:.2f}")
            print(f"Largest Win:            ${overall['largest_win']:.2f}")
            print(f"Largest Loss:           ${overall['largest_loss']:.2f}")
            print(f"Max Consecutive Wins:   {overall['max_consecutive_wins']}")
            print(f"Max Consecutive Losses: {overall['max_consecutive_losses']}")
            print(f"Avg Trade Duration:     {overall['avg_duration_minutes']:.1f} minutes")

        # Risk Metrics
        if 'risk_metrics' in stats:
            risk = stats['risk_metrics']
            print("\n" + "-"*80)
            print("RISK METRICS")
            print("-"*80)
            print(f"Maximum Drawdown:       ${risk['max_drawdown']:.2f} ({risk['max_drawdown_percent']:.2f}%)")
            print(f"Sharpe Ratio:           {risk['sharpe_ratio']:.3f}")
            print(f"Peak Equity:            ${risk['peak_equity']:.2f}")
            print(f"Final Equity:           ${risk['final_equity']:.2f}")

        # By Symbol
        if 'by_symbol' in stats and stats['by_symbol']:
            print("\n" + "-"*80)
            print("PERFORMANCE BY SYMBOL")
            print("-"*80)
            print(f"{'Symbol':<12} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'Win Rate':<10} {'Net P/L':<12}")
            print("-"*80)
            for symbol, data in sorted(stats['by_symbol'].items(), key=lambda x: x[1]['net_profit'], reverse=True):
                print(f"{symbol:<12} {data['total_trades']:<8} {data['winning_trades']:<6} {data['losing_trades']:<8} "
                      f"{data['win_rate']:>6.2f}%   ${data['net_profit']:>10.2f}")

        # By Strategy
        if 'by_strategy' in stats and stats['by_strategy']:
            print("\n" + "-"*80)
            print("PERFORMANCE BY STRATEGY TYPE")
            print("-"*80)
            print(f"{'Strategy':<12} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'Win Rate':<10} {'Net P/L':<12}")
            print("-"*80)
            for strategy, data in sorted(stats['by_strategy'].items()):
                strategy_name = {'TB': 'True Breakout', 'FB': 'False Breakout', 'UNKNOWN': 'Unknown'}.get(strategy, strategy)
                print(f"{strategy_name:<12} {data['total_trades']:<8} {data['winning_trades']:<6} {data['losing_trades']:<8} "
                      f"{data['win_rate']:>6.2f}%   ${data['net_profit']:>10.2f}")

        # By Range
        if 'by_range' in stats and stats['by_range']:
            print("\n" + "-"*80)
            print("PERFORMANCE BY RANGE CONFIGURATION")
            print("-"*80)
            print(f"{'Range':<12} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'Win Rate':<10} {'Net P/L':<12}")
            print("-"*80)
            for range_id, data in sorted(stats['by_range'].items()):
                print(f"{range_id:<12} {data['total_trades']:<8} {data['winning_trades']:<6} {data['losing_trades']:<8} "
                      f"{data['win_rate']:>6.2f}%   ${data['net_profit']:>10.2f}")

        # By Confirmation
        if 'by_confirmation' in stats and stats['by_confirmation']:
            print("\n" + "-"*80)
            print("PERFORMANCE BY CONFIRMATION TYPE")
            print("-"*80)
            print(f"{'Confirmation':<20} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'Win Rate':<10} {'Net P/L':<12}")
            print("-"*80)
            for conf_type, data in sorted(stats['by_confirmation'].items()):
                conf_name = conf_type.replace('_', ' ').title()
                print(f"{conf_name:<20} {data['total_trades']:<8} {data['winning_trades']:<6} {data['losing_trades']:<8} "
                      f"{data['win_rate']:>6.2f}%   ${data['net_profit']:>10.2f}")

        # Time-based analysis
        if 'by_time' in stats:
            time_stats = stats['by_time']

            if 'by_day_of_week' in time_stats and time_stats['by_day_of_week']:
                print("\n" + "-"*80)
                print("PERFORMANCE BY DAY OF WEEK")
                print("-"*80)
                print(f"{'Day':<12} {'Trades':<8} {'Win Rate':<10} {'Net P/L':<12}")
                print("-"*80)
                day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                for day in day_order:
                    if day in time_stats['by_day_of_week']:
                        data = time_stats['by_day_of_week'][day]
                        print(f"{day:<12} {data['total_trades']:<8} {data['win_rate']:>6.2f}%   ${data['net_profit']:>10.2f}")

            if 'by_hour_of_day' in time_stats and time_stats['by_hour_of_day']:
                print("\n" + "-"*80)
                print("PERFORMANCE BY HOUR OF DAY (UTC)")
                print("-"*80)
                print(f"{'Hour':<8} {'Trades':<8} {'Win Rate':<10} {'Net P/L':<12}")
                print("-"*80)
                for hour in sorted(time_stats['by_hour_of_day'].keys()):
                    data = time_stats['by_hour_of_day'][hour]
                    print(f"{hour:02d}:00   {data['total_trades']:<8} {data['win_rate']:>6.2f}%   ${data['net_profit']:>10.2f}")

        print("\n" + "="*80)

    def export_to_csv(self, trades: List[Dict], stats: Dict, output_file: str):
        """Export trades and statistics to CSV file"""
        try:
            # Export individual trades
            trades_file = output_file.replace('.csv', '_trades.csv')
            with open(trades_file, 'w', newline='') as f:
                if trades:
                    fieldnames = trades[0].keys()
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(trades)

            print(f"\n✓ Trades exported to: {trades_file}")

            # Export summary statistics
            summary_file = output_file.replace('.csv', '_summary.csv')
            with open(summary_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Metric', 'Value'])

                if 'overall' in stats:
                    writer.writerow(['=== OVERALL PERFORMANCE ===', ''])
                    for key, value in stats['overall'].items():
                        writer.writerow([key.replace('_', ' ').title(), value])

                if 'risk_metrics' in stats:
                    writer.writerow(['', ''])
                    writer.writerow(['=== RISK METRICS ===', ''])
                    for key, value in stats['risk_metrics'].items():
                        writer.writerow([key.replace('_', ' ').title(), value])

            print(f"✓ Summary exported to: {summary_file}")

        except Exception as e:
            self.logger.error(f"Error exporting to CSV: {e}")


def main():
    """Main function to run the analysis"""
    parser = argparse.ArgumentParser(
        description='Analyze MT5 trading history',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze all available history
  python analyze_trading_history.py

  # Analyze last 30 days
  python analyze_trading_history.py --days 30

  # Analyze specific symbols
  python analyze_trading_history.py --symbols EURUSD,GBPUSD,USDJPY

  # Export to CSV
  python analyze_trading_history.py --output analysis.csv --format csv

  # Both console and CSV output
  python analyze_trading_history.py --output analysis.csv --format both
        """
    )

    parser.add_argument('--days', type=int, default=None,
                        help='Number of days to look back (default: all available)')
    parser.add_argument('--output', type=str, default=None,
                        help='Output file path for CSV export (optional)')
    parser.add_argument('--format', type=str, choices=['console', 'csv', 'both'], default='console',
                        help='Output format (default: console)')
    parser.add_argument('--symbols', type=str, default=None,
                        help='Comma-separated list of symbols to analyze (default: all)')

    args = parser.parse_args()

    # Parse symbols list
    symbols = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(',')]

    # Load configuration
    config = TradingConfig()

    # Connect to MT5
    connector = MT5Connector(config.mt5)
    if not connector.connect():
        print("❌ Failed to connect to MT5")
        return 1

    print("✓ Connected to MT5")
    print(f"Magic Number: {config.advanced.magic_number}")

    # Create analyzer
    analyzer = TradingAnalyzer(connector, config.advanced.magic_number)

    # Fetch trade history
    print(f"\nFetching trade history...")
    if args.days:
        print(f"Looking back: {args.days} days")
    else:
        print("Looking back: All available history")

    if symbols:
        print(f"Filtering symbols: {', '.join(symbols)}")

    trades = analyzer.fetch_trade_history(days_back=args.days, symbols=symbols)

    if not trades:
        print("\n❌ No trades found matching the criteria")
        connector.disconnect()
        return 1

    print(f"✓ Found {len(trades)} closed trades")

    # Calculate statistics
    print("\nCalculating statistics...")
    stats = analyzer.calculate_statistics(trades)
    print("✓ Statistics calculated")

    # Output results
    if args.format in ['console', 'both']:
        analyzer.print_statistics(stats)

    if args.format in ['csv', 'both']:
        if not args.output:
            print("\n❌ Error: --output must be specified when using CSV format")
            connector.disconnect()
            return 1

        analyzer.export_to_csv(trades, stats, args.output)

    # Disconnect
    connector.disconnect()
    print("\n✓ Analysis complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())

