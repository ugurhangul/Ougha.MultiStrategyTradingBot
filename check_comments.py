import pickle

trades = pickle.load(open('backtest_trades.pkl', 'rb'))

print(f"Total trades: {len(trades)}")
print("\nSample comments:")
for i, t in enumerate(trades[:20]):
    print(f"{i+1}. Symbol: {t['symbol']:<10} Comment: {t['comment']}")

print("\n\nLooking for x100/x10 trades:")
x_trades = [t for t in trades if 'x100' in t['symbol'] or 'x10' in t['symbol']]
print(f"Found {len(x_trades)} trades with x100/x10 in symbol name")
for i, t in enumerate(x_trades[:10]):
    print(f"{i+1}. Symbol: {t['symbol']:<15} Comment: {t['comment']}")

