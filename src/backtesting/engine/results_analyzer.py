"""
Results Analyzer for Custom Backtesting Engine.

Analyzes backtest results and generates performance metrics.
"""
from typing import Dict, List
import pandas as pd
import numpy as np
from datetime import datetime

from src.utils.logger import get_logger


class ResultsAnalyzer:
    """
    Analyze backtest results and generate performance metrics.
    
    Calculates:
    - Total return, profit/loss
    - Sharpe ratio, Sortino ratio
    - Maximum drawdown
    - Win rate, profit factor
    - Per-strategy metrics
    """
    
    def __init__(self):
        """Initialize results analyzer."""
        self.logger = get_logger()
    
    def analyze(self, results: Dict) -> Dict:
        """
        Analyze backtest results.
        
        Args:
            results: Results dictionary from BacktestController
            
        Returns:
            Dictionary with performance metrics
        """
        equity_curve = results.get('equity_curve', [])
        trade_log = results.get('trade_log', [])
        
        if not equity_curve:
            self.logger.warning("No equity curve data to analyze")
            return {}
        
        # Convert to DataFrame for easier analysis
        equity_df = pd.DataFrame(equity_curve)
        
        # Calculate metrics
        metrics = {
            'total_return': self._calculate_total_return(equity_df),
            'total_profit': results.get('total_profit', 0),
            'profit_percent': results.get('profit_percent', 0),
            'max_drawdown': self._calculate_max_drawdown(equity_df),
            'sharpe_ratio': self._calculate_sharpe_ratio(equity_df),
            'total_trades': len(trade_log),
            'final_balance': results.get('final_balance', 0),
            'final_equity': results.get('final_equity', 0),
            'open_positions': results.get('open_positions', 0),
        }
        
        # Add trade statistics if available
        if trade_log:
            trade_stats = self._analyze_trades(trade_log)
            metrics.update(trade_stats)

            # Add per-symbol breakdown
            metrics['per_symbol'] = self._analyze_by_symbol(trade_log)

            # Add per-strategy breakdown (extracted from comment field)
            metrics['per_strategy'] = self._analyze_by_strategy(trade_log)

        return metrics
    
    def _calculate_total_return(self, equity_df: pd.DataFrame) -> float:
        """Calculate total return percentage."""
        if len(equity_df) < 2:
            return 0.0
        
        initial_equity = equity_df.iloc[0]['equity']
        final_equity = equity_df.iloc[-1]['equity']
        
        if initial_equity == 0:
            return 0.0
        
        return ((final_equity - initial_equity) / initial_equity) * 100.0
    
    def _calculate_max_drawdown(self, equity_df: pd.DataFrame) -> float:
        """Calculate maximum drawdown percentage."""
        if len(equity_df) < 2:
            return 0.0
        
        equity = equity_df['equity'].values
        
        # Calculate running maximum
        running_max = np.maximum.accumulate(equity)
        
        # Calculate drawdown at each point
        drawdown = (equity - running_max) / running_max * 100.0
        
        # Return maximum drawdown (most negative value)
        return abs(drawdown.min())
    
    def _calculate_sharpe_ratio(self, equity_df: pd.DataFrame, risk_free_rate: float = 0.0) -> float:
        """
        Calculate Sharpe ratio.
        
        Args:
            equity_df: Equity curve DataFrame
            risk_free_rate: Annual risk-free rate (default 0%)
            
        Returns:
            Sharpe ratio
        """
        if len(equity_df) < 2:
            return 0.0
        
        # Calculate returns
        equity = equity_df['equity'].values
        returns = np.diff(equity) / equity[:-1]
        
        if len(returns) == 0:
            return 0.0
        
        # Calculate excess returns
        excess_returns = returns - (risk_free_rate / 252)  # Assuming daily data
        
        # Calculate Sharpe ratio
        if np.std(excess_returns) == 0:
            return 0.0
        
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
    
    def _analyze_trades(self, trade_log: List[Dict]) -> Dict:
        """
        Analyze trade statistics.

        Args:
            trade_log: List of trade dictionaries

        Returns:
            Dictionary with trade statistics
        """
        if not trade_log:
            return {}

        # Extract profits
        profits = [trade.get('profit', 0) for trade in trade_log]

        winning_trades = [p for p in profits if p > 0]
        losing_trades = [p for p in profits if p < 0]

        total_wins = len(winning_trades)
        total_losses = len(losing_trades)
        total_trades = len(profits)

        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

        avg_win = np.mean(winning_trades) if winning_trades else 0
        avg_loss = abs(np.mean(losing_trades)) if losing_trades else 0

        # Calculate profit factor
        if losing_trades:
            profit_factor = sum(winning_trades) / abs(sum(losing_trades))
        elif winning_trades:
            profit_factor = float('inf')
        else:
            profit_factor = 0

        # Calculate largest win/loss
        largest_win = max(winning_trades) if winning_trades else 0
        largest_loss = abs(min(losing_trades)) if losing_trades else 0

        # Calculate consecutive wins/losses
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0

        for profit in profits:
            if profit > 0:
                consecutive_wins += 1
                consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
            elif profit < 0:
                consecutive_losses += 1
                consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

        return {
            'total_trades': total_trades,
            'winning_trades': total_wins,
            'losing_trades': total_losses,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'largest_win': largest_win,
            'largest_loss': largest_loss,
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses,
        }

    def _analyze_by_symbol(self, trade_log: List[Dict]) -> Dict:
        """
        Analyze trades grouped by symbol.

        Args:
            trade_log: List of trade dictionaries

        Returns:
            Dictionary with per-symbol statistics
        """
        if not trade_log:
            return {}

        # Group trades by symbol
        symbol_trades = {}
        for trade in trade_log:
            symbol = trade.get('symbol', 'UNKNOWN')
            if symbol not in symbol_trades:
                symbol_trades[symbol] = []
            symbol_trades[symbol].append(trade)

        # Analyze each symbol
        results = {}
        for symbol, trades in symbol_trades.items():
            profits = [t.get('profit', 0) for t in trades]
            winning = [p for p in profits if p > 0]
            losing = [p for p in profits if p < 0]

            total_profit = sum(profits)
            total_trades = len(trades)
            win_count = len(winning)
            loss_count = len(losing)
            win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
            profit_factor = (sum(winning) / abs(sum(losing))) if losing else (float('inf') if winning else 0)

            results[symbol] = {
                'total_trades': total_trades,
                'total_profit': total_profit,
                'winning_trades': win_count,
                'losing_trades': loss_count,
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'avg_profit': total_profit / total_trades if total_trades > 0 else 0,
            }

        return results

    def _analyze_by_strategy(self, trade_log: List[Dict]) -> Dict:
        """
        Analyze trades grouped by strategy (extracted from comment field).

        Args:
            trade_log: List of trade dictionaries

        Returns:
            Dictionary with per-strategy statistics
        """
        if not trade_log:
            return {}

        # Group trades by strategy (from comment field)
        strategy_trades = {}
        for trade in trade_log:
            comment = trade.get('comment', '')
            # Extract strategy from comment (format: "symbol|strategy_key")
            # e.g., "EURUSD|fakeout_4H_5M" -> "fakeout_4H_5M"
            if '|' in comment:
                parts = comment.split('|')
                strategy_key = parts[1] if len(parts) > 1 else 'UNKNOWN'
            else:
                strategy_key = 'UNKNOWN'

            if strategy_key not in strategy_trades:
                strategy_trades[strategy_key] = []
            strategy_trades[strategy_key].append(trade)

        # Analyze each strategy
        results = {}
        for strategy_key, trades in strategy_trades.items():
            profits = [t.get('profit', 0) for t in trades]
            winning = [p for p in profits if p > 0]
            losing = [p for p in profits if p < 0]

            total_profit = sum(profits)
            total_trades = len(trades)
            win_count = len(winning)
            loss_count = len(losing)
            win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
            profit_factor = (sum(winning) / abs(sum(losing))) if losing else (float('inf') if winning else 0)

            results[strategy_key] = {
                'total_trades': total_trades,
                'total_profit': total_profit,
                'winning_trades': win_count,
                'losing_trades': loss_count,
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'avg_profit': total_profit / total_trades if total_trades > 0 else 0,
            }

        return results

