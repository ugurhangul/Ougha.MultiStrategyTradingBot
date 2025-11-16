"""Quick diagnostic for BTCXAU and BTCXAG symbols."""

import MetaTrader5 as mt5

if not mt5.initialize():
    print(f"Failed to initialize MT5: {mt5.last_error()}")
    exit(1)

for symbol in ['BTCXAU', 'BTCXAG']:
    print(f"\n{'='*80}")
    print(f"SYMBOL: {symbol}")
    print('='*80)
    
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"❌ Symbol {symbol} not found")
        continue
    
    print(f"Currency Base:     {info.currency_base}")
    print(f"Currency Profit:   {info.currency_profit}")
    print(f"Contract Size:     {info.trade_contract_size}")
    print(f"Tick Value:        {info.trade_tick_value:.8f}")
    print(f"Tick Size:         {info.trade_tick_size:.8f}")
    print(f"Point:             {info.point:.8f}")
    print(f"Digits:            {info.digits}")
    
    tick = mt5.symbol_info_tick(symbol)
    if tick:
        print(f"Current Bid:       {tick.bid:.{info.digits}f}")
        print(f"Current Ask:       {tick.ask:.{info.digits}f}")

mt5.shutdown()

