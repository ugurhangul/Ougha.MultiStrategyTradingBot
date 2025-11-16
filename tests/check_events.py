import hftbacktest.types as hbt_types

members = [m for m in dir(hbt_types) if 'EVENT' in m and not m.startswith('_')]
for m in sorted(members):
    val = getattr(hbt_types, m)
    if isinstance(val, int):
        print(f'{m}: {hex(val)}')

