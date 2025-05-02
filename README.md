# Smart Order Router Backtest (Cont & Kukanov)

This project implements a backtest for a smart order routing strategy using the static cost model proposed by **Cont & Kukanov (2014)**. It allocates a 5,000-share buy order across multiple trading venues based on real-time quote data and compares performance against three common baselines.


## Files

- `backtest.py` – Full standalone script (uses only `numpy`, `pandas`, and standard libraries)  
- `results.png` – Cumulative cost over time plot (9-minute execution window)  
- `README.md` – This file


##  How It Works

- Replays historical L1 data from `l1_day.csv`
- Implements the **static allocator** based on `allocator_pseudocode.txt`
- Searches over parameters:
  - `lambda_over` (overfill penalty)
  - `lambda_under` (underfill penalty)
  - `theta_queue` (queue risk penalty)
- Optimizes total execution cost
- Compares results with:
  1. **Best Ask Baseline** (greedy fill at lowest quote)
  2. **TWAP** (equal-sized buckets per minute)
  3. **VWAP** (weighted by displayed ask sizes)


## 📊 Output

- Prints a JSON object containing:
  - Best parameters
  - Total cost and average fill price for optimal strategy and baselines
  - Savings (in basis points) vs. each baseline
- Saves `results.png`:  
  Cumulative cost plotted for Best Ask, TWAP, and VWAP baselines

![results](results.png)


## 📈 Example JSON Output

```json
{
  "best_params": {
    "lambda_over": 0.0,
    "lambda_under": 0.0,
    "theta_queue": 0.0
  },
  "optimal": {
    "total_cost": 1114117.28,
    "avg_fill_price": 222.823456
  },
  "baseline_best_ask": {
    "total_cost": 1114117.28,
    "avg_fill_price": 222.823456
  },
  "baseline_TWAP": {
    "total_cost": 1115304.1,
    "avg_fill_price": 223.06082
  },
  "baseline_VWAP": {
    "total_cost": 1115198.55,
    "avg_fill_price": 223.03971
  },
  "savings_vs_best_ask_bps": 0.0,
  "savings_vs_TWAP_bps": 10.64,
  "savings_vs_VWAP_bps": 9.7
}
