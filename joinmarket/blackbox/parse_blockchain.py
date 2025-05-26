def detect_coinjoin_txs(tx_map):
    """
    Identify potential CoinJoin transactions using blockchain-only heuristics.
    
    Args:
        tx_map: Dictionary mapping txids to transaction data
        
    Returns:
        List of tuples (txid, tx, block) for likely CoinJoin transactions
    """
    if not tx_map:
        print("Warning: Empty transaction map provided to detect_coinjoin_txs")
        return []
        
    coinjoins = []
    skipped_transactions = 0
    processing_errors = 0
    
    for txid, info in tx_map.items():
        try:
            tx = info.get('tx')
            if not tx:
                skipped_transactions += 1
                continue
                
            block = info.get('block')
            if not block:
                skipped_transactions += 1
                continue
                
            # Skip transactions with too few inputs or outputs
            if not tx.get('vin') or not tx.get('vout') or len(tx['vin']) < 2 or len(tx['vout']) < 2:
                continue
                
            # Find repeated output values (classic CoinJoin fingerprint)
            # Try to handle transactions where 'value' might be missing in some outputs
            try:
                values = [v.get('value', 0) for v in tx['vout'] if 'value' in v]
                if not values:
                    continue
                    
                # Count repeated values - potential CoinJoin outputs
                repeats = {v: values.count(v) for v in set(values) if values.count(v) > 1}
                if not repeats:
                    continue
                    
                # Find the most common output value - likely the CoinJoin amount
                cj_value = max(repeats.items(), key=lambda x: x[1])[0]
                
                # Only consider as CoinJoin if there are multiple outputs with the same value
                if repeats[cj_value] < 2:
                    continue
                    
                # Additional heuristic: at least as many inputs as equal outputs
                if len(tx['vin']) < repeats[cj_value]:
                    continue
                    
                coinjoins.append((txid, tx, block))
                
            except (KeyError, TypeError, ValueError) as e:
                print(f"Error processing transaction {txid}: {e}")
                processing_errors += 1
                continue
                
        except Exception as e:
            print(f"Unexpected error processing transaction {txid}: {e}")
            processing_errors += 1
            continue
    
    if skipped_transactions > 0:
        print(f"Skipped {skipped_transactions} transactions due to missing data")
    if processing_errors > 0:
        print(f"Encountered {processing_errors} errors while processing transactions")
        
    print(f"Found {len(coinjoins)} potential CoinJoin transactions out of {len(tx_map)} total transactions")
    return coinjoins
