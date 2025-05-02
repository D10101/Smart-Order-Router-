import pandas as pd
import numpy as np
import json

# Load and preprocess data
df = pd.read_csv('l1_day.csv', usecols=['ts_event', 'publisher_id', 'ask_px_00', 'ask_sz_00'])
df['ts_event'] = pd.to_datetime(df['ts_event'])
df = df.sort_values('ts_event')
# Keep only the first message per (ts_event, publisher_id)
df = df.drop_duplicates(subset=['publisher_id', 'ts_event'], keep='first')
events = list(df.itertuples(index=False, name=None))  # list of (ts_event, publisher_id, ask_px_00, ask_sz_00)

# Static Cont-Kukanov allocation (search in 100-share increments)
def allocate(order_size, venues, λ_over, λ_under, θ_queue):
    step = 100
    # Generate all feasible splits across venues in `step` increments
    splits = [[]]
    for v in range(len(venues)):
        new_splits = []
        for alloc in splits:
            used = sum(alloc)
            remaining = order_size - used
            max_q = min(remaining, venues[v]['ask_size'])
            q = 0
            while q <= max_q:
                new_splits.append(alloc + [q])
                q += step
        splits = new_splits
    # Evaluate cost for each complete allocation (sum == order_size)
    best_cost = float('inf')
    best_split = None
    for alloc in splits:
        if sum(alloc) != order_size:
            continue
        executed = 0
        cash_spent = 0.0
        for i, q in enumerate(alloc):
            v = venues[i]
            executed_i = min(q, v['ask_size'])
            executed += executed_i
            cash_spent += executed_i * (v['ask_price'] + v['fee'])
            maker_qty = max(q - executed_i, 0)  # shares posted but not filled
            cash_spent -= maker_qty * v['rebate']
        underfill = max(order_size - executed, 0)
        overfill = max(executed - order_size, 0)
        cost_penalty = λ_under * underfill + λ_over * overfill
        risk_penalty = θ_queue * (underfill + overfill)
        total_cost = cash_spent + cost_penalty + risk_penalty
        if total_cost < best_cost:
            best_cost = total_cost
            best_split = alloc
    # If no exact split found (not enough liquidity to fill order), allocate all available
    if best_split is None:
        best_split = []
        used = 0
        for v in venues:
            take = min(order_size - used, v['ask_size'])
            best_split.append(take)
            used += take
    return best_split

# Simulate execution of the strategy for given parameters
def simulate_strategy(λ_over, λ_under, θ_queue):
    remaining = 5000
    total_cost = 0.0
    filled = 0
    current_asks = {}  # track current best ask and size per venue
    for ts, pub, ask_px, ask_sz in events:
        current_asks[pub] = (ask_px, ask_sz)
        if remaining <= 0:
            break
        # Build venues list for allocator (with fee and rebate for each)
        venues = []
        for pid, (price, size) in current_asks.items():
            venues.append({
                'ask_price': price,
                'ask_size': size,
                'fee': 0.003,    # assume $0.003/share taker fee
                'rebate': 0.002  # assume $0.002/share maker rebate
            })
        # Get optimal split for current snapshot
        split = allocate(remaining, venues, λ_over, λ_under, θ_queue)
        # Execute immediate taker portion up to displayed size on each venue
        executed_now = 0
        for alloc_q, venue in zip(split, venues):
            fill = min(alloc_q, venue['ask_size'])
            if fill > 0:
                executed_now += fill
                total_cost += fill * (venue['ask_price'] + venue['fee'])
        remaining -= executed_now
        filled += executed_now
    avg_price = total_cost / filled if filled > 0 else 0.0
    return filled, total_cost, avg_price

# Baseline (i): Take the best ask (greedy across venues)
def simulate_baseline_best_ask():
    remaining = 5000
    total_cost = 0.0
    filled = 0
    current_asks = {}
    for ts, pub, ask_px, ask_sz in events:
        current_asks[pub] = (ask_px, ask_sz)
        if remaining <= 0:
            break
        # Find lowest ask price among all venues
        best_price = None
        best_venues = []
        for pid, (price, size) in current_asks.items():
            if best_price is None or price < best_price:
                best_price = price
                best_venues = [(pid, size)]
            elif price == best_price:
                best_venues.append((pid, size))
        if best_price is None:
            continue
        # Take from all venues at the best price
        avail = sum(sz for _, sz in best_venues)
        if avail == 0:
            continue
        to_buy = min(remaining, avail)
        qty = to_buy
        for pid, size in best_venues:
            if qty <= 0:
                break
            take = min(qty, size)
            if take > 0:
                total_cost += take * (best_price + 0.003)
                filled += take
                qty -= take
        remaining -= to_buy
    avg_price = total_cost / filled if filled > 0 else 0.0
    return filled, total_cost, avg_price

# Baseline (ii): TWAP (even split across 60-second intervals)
def simulate_baseline_twap():
    if not events:
        return 0, 0.0, 0.0
    start_time = events[0][0]
    end_time = events[-1][0]
    total_seconds = (end_time - start_time).total_seconds()
    n_buckets = int(np.ceil(total_seconds / 60.0))
    # Divide 5000 shares evenly into 60s buckets
    base_shares = 5000 // n_buckets
    remainder = 5000 % n_buckets
    bucket_targets = [base_shares + (1 if i < remainder else 0) for i in range(n_buckets)]
    remaining = 5000
    total_cost = 0.0
    filled = 0
    current_asks = {}
    current_bucket = 0
    bucket_quota = bucket_targets[0] if n_buckets > 0 else 0
    for ts, pub, ask_px, ask_sz in events:
        current_asks[pub] = (ask_px, ask_sz)
        bucket_idx = int((ts - start_time).total_seconds() // 60)
        if bucket_idx != current_bucket:
            # Carry over unfilled shares to next bucket
            if bucket_quota > 0 and current_bucket < n_buckets - 1:
                bucket_targets[current_bucket + 1] += bucket_quota
            current_bucket = bucket_idx
            bucket_quota = bucket_targets[current_bucket] if current_bucket < n_buckets else 0
        if remaining <= 0 or bucket_quota <= 0:
            continue
        # Take available shares at the best ask up to the bucket's quota
        best_price = None
        best_venues = []
        for pid, (price, size) in current_asks.items():
            if best_price is None or price < best_price:
                best_price = price
                best_venues = [(pid, size)]
            elif price == best_price:
                best_venues.append((pid, size))
        if best_price is None:
            continue
        avail = sum(sz for _, sz in best_venues)
        if avail == 0:
            continue
        to_buy = min(bucket_quota, avail)
        qty = to_buy
        for pid, size in best_venues:
            if qty <= 0:
                break
            take = min(qty, size)
            if take > 0:
                total_cost += take * (best_price + 0.003)
                filled += take
                qty -= take
        bucket_quota -= to_buy
        remaining -= to_buy
    avg_price = total_cost / filled if filled > 0 else 0.0
    return filled, total_cost, avg_price

# Baseline (iii): VWAP (allocate to 60s buckets weighted by total displayed size)
def simulate_baseline_vwap():
    if not events:
        return 0, 0.0, 0.0
    start_time = events[0][0]
    end_time = events[-1][0]
    total_seconds = (end_time - start_time).total_seconds()
    n_buckets = int(np.ceil(total_seconds / 60.0))
    # Calculate total displayed ask size per 60s bucket as weight
    bucket_weights = [0] * n_buckets
    for ts, pub, ask_px, ask_sz in events:
        idx = int((ts - start_time).total_seconds() // 60)
        if 0 <= idx < n_buckets:
            bucket_weights[idx] += ask_sz
    total_weight = sum(bucket_weights)
    # Allocate shares to buckets in proportion to their weight
    bucket_targets = [0] * n_buckets
    allocated = 0
    fractional = []
    for i, w in enumerate(bucket_weights):
        if total_weight > 0:
            target_float = 5000 * w / total_weight
        else:
            target_float = 0
        shares = int(np.floor(target_float))
        bucket_targets[i] = shares
        allocated += shares
        fractional.append((target_float - shares, i))
    # Distribute any remaining shares to buckets with largest fractional part
    remainder = 5000 - allocated
    fractional.sort(reverse=True, key=lambda x: x[0])
    for j in range(remainder):
        if j < len(fractional):
            bucket_targets[fractional[j][1]] += 1
    remaining = 5000
    total_cost = 0.0
    filled = 0
    current_asks = {}
    current_bucket = 0
    bucket_quota = bucket_targets[0] if n_buckets > 0 else 0
    for ts, pub, ask_px, ask_sz in events:
        current_asks[pub] = (ask_px, ask_sz)
        bucket_idx = int((ts - start_time).total_seconds() // 60)
        if bucket_idx != current_bucket:
            if bucket_quota > 0 and current_bucket < n_buckets - 1:
                bucket_targets[current_bucket + 1] += bucket_quota
            current_bucket = bucket_idx
            bucket_quota = bucket_targets[current_bucket] if current_bucket < n_buckets else 0
        if remaining <= 0 or bucket_quota <= 0:
            continue
        # Take available shares at best ask up to the bucket's target
        best_price = None
        best_venues = []
        for pid, (price, size) in current_asks.items():
            if best_price is None or price < best_price:
                best_price = price
                best_venues = [(pid, size)]
            elif price == best_price:
                best_venues.append((pid, size))
        if best_price is None:
            continue
        avail = sum(sz for _, sz in best_venues)
        if avail == 0:
            continue
        to_buy = min(bucket_quota, avail)
        qty = to_buy
        for pid, size in best_venues:
            if qty <= 0:
                break
            take = min(qty, size)
            if take > 0:
                total_cost += take * (best_price + 0.003)
                filled += take
                qty -= take
        bucket_quota -= to_buy
        remaining -= to_buy
    avg_price = total_cost / filled if filled > 0 else 0.0
    return filled, total_cost, avg_price

# Grid search over a small set of λ_over, λ_under, θ_queue values
param_candidates = [0.0, 0.005, 0.01]
best_params = None
best_cost = float('inf')
best_avg_price = 0.0
for λo in param_candidates:
    for λu in param_candidates:
        for θ in [0.0, 0.001, 0.005]:
            filled, cost, avg_price = simulate_strategy(λo, λu, θ)
            # Penalize incomplete fills heavily (should not happen within provided data window)
            if filled < 5000:
                cost += (5000 - filled) * float(df['ask_px_00'].max()) * 2
                avg_price = cost / 5000
            if cost < best_cost:
                best_cost = cost
                best_avg_price = avg_price
                best_params = (λo, λu, θ)

# Compute baseline results
_, cost_best, avg_best = simulate_baseline_best_ask()
_, cost_twap, avg_twap = simulate_baseline_twap()
_, cost_vwap, avg_vwap = simulate_baseline_vwap()

# Compute savings in basis points (bps) versus each baseline
savings_best_bps = ((avg_best - best_avg_price) / avg_best * 10000) if avg_best > 0 else 0.0
savings_twap_bps = ((avg_twap - best_avg_price) / avg_twap * 10000) if avg_twap > 0 else 0.0
savings_vwap_bps = ((avg_vwap - best_avg_price) / avg_vwap * 10000) if avg_vwap > 0 else 0.0

# Prepare output JSON
output = {
    "best_params": {
        "lambda_over": best_params[0],
        "lambda_under": best_params[1],
        "theta_queue": best_params[2]
    },
    "optimal": {
        "total_cost": round(best_cost, 2),
        "avg_fill_price": round(best_avg_price, 6)
    },
    "baseline_best_ask": {
        "total_cost": round(cost_best, 2),
        "avg_fill_price": round(avg_best, 6)
    },
    "baseline_TWAP": {
        "total_cost": round(cost_twap, 2),
        "avg_fill_price": round(avg_twap, 6)
    },
    "baseline_VWAP": {
        "total_cost": round(cost_vwap, 2),
        "avg_fill_price": round(avg_vwap, 6)
    },
    "savings_vs_best_ask_bps": round(savings_best_bps, 2),
    "savings_vs_TWAP_bps": round(savings_twap_bps, 2),
    "savings_vs_VWAP_bps": round(savings_vwap_bps, 2)
}

print(json.dumps(output))