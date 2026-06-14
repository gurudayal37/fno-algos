import math


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S, K, T, r, sigma, option_type="CE"):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if option_type == "CE" else max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "CE":
        return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def bs_delta(S, K, T, r, sigma, option_type="CE"):
    if T <= 0 or sigma <= 0:
        if option_type == "CE":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) if option_type == "CE" else norm_cdf(d1) - 1.0


def implied_vol(price, S, K, T, r, option_type="CE", lo=0.001, hi=5.0, tol=1e-4, max_iter=100):
    """Bisection search for the implied volatility that reprices `price`."""
    if price <= 0 or T <= 0:
        return None

    intrinsic = max(S - K, 0.0) if option_type == "CE" else max(K - S, 0.0)
    if price <= intrinsic:
        return lo

    if bs_price(S, K, T, r, hi, option_type) < price:
        return hi

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        p = bs_price(S, K, T, r, mid, option_type)
        if abs(p - price) < tol:
            return mid
        if p < price:
            lo = mid
        else:
            hi = mid
    return mid


def delta_for_premium(price, S, K, T, r, option_type="CE"):
    """Returns the Black-Scholes delta implied by an observed option premium."""
    iv = implied_vol(price, S, K, T, r, option_type)
    if iv is None:
        return None
    return bs_delta(S, K, T, r, iv, option_type)
