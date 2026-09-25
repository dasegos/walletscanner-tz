# Side imports
from enum import Enum


# FROM ERC-20: Token Standard; source: https://eips.ethereum.org/EIPS/eip-20
# "A token contract which creates new tokens SHOULD trigger a Transfer event with 
# the _from address set to 0x0 when tokens are created."
# => Transfer event has `_from` set to `0x0` when it's deposit
# => Transfer event has `_to` set to `0x0` when it's withdraw

# FROM ERC-1155: Multi Token Standard; source: https://eips.ethereum.org/EIPS/eip-1155
# "When minting/creating tokens, the `_from` argument MUST be set to `0x0` (i.e. zero address)." 
# => PositionSplit event has `_from` set to `0x0`.
# "When burning/destroying tokens, the `_to` argument MUST be set to `0x0` (i.e. zero address)."
# => PositionMerge & PayoutRedemption events have `_to` set to `0x0`.


class TransactionType(str, Enum):
    TRADE     = "TRADE"     # Transfer/TransferSingle/TransferBatch; _from ≠ 0x0, _to ≠ 0x0 
    DEPOSIT   = "DEPOSIT"   # Transfer; _from = 0x0, _to ≠ 0x0
    WITHDRAW  = "WITHDRAW"  # Transfer; _from ≠ 0x0, _to = 0x0
    SPLIT     = "SPLIT"     # TransferSingle/TransferBatch; _from = 0x0, _to ≠ 0x0
    MERGE     = "MERGE"     # TransferSingle/TransferBatch; _from ≠ 0x0, _to = 0x0
    REDEEM    = "REDEEM"    # TransferSingle/TransferBatch; _from ≠ 0x0, _to = 0x0


class AssetType(str, Enum):
    USDT  = "USDT"  # pUSD on https://polymarket.com
    SHARE = "SHARE" # YES/NO tokens