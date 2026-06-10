import time
import requests
import json
from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN, logger, check_config

class DhanClientWrapper:
    """
    Wrapper around the DhanHQ API v2 endpoints using direct HTTP requests.
    Handles rate-limiting retries using exponential backoff.
    """
    def __init__(self):
        errors = check_config()
        if errors:
            for err in errors:
                logger.error(err)
            raise ValueError("Invalid configuration. Please check your .env file.")
        
        self.access_token = DHAN_ACCESS_TOKEN
        self.client_id = DHAN_CLIENT_ID
        self.base_url = "https://api.dhan.co/v2"
        self.headers = {
            "access-token": self.access_token,
            "Content-Type": "application/json"
        }
        logger.info("Dhan HTTP client wrapper initialized successfully.")

    def _post_request(self, endpoint, payload, max_retries=5, initial_backoff=1.0):
        """Helper to post requests to Dhan with rate limit retries."""
        url = f"{self.base_url}{endpoint}"
        retries = 0
        backoff = initial_backoff
        
        while retries <= max_retries:
            try:
                response = requests.post(url, headers=self.headers, data=json.dumps(payload), timeout=15)
                
                # Check for rate limits or other HTTP errors
                if response.status_code == 429:
                    retries += 1
                    logger.warning(f"HTTP 429 Rate Limit hit. Retrying {retries}/{max_retries} in {backoff:.2f}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                    
                if response.status_code != 200:
                    logger.error(f"HTTP Error {response.status_code}: {response.text}")
                    return {"status": "failure", "error": f"HTTP {response.status_code}", "message": response.text}
                
                response_json = response.json()
                
                # Check for API rate limit errors in JSON structure
                if isinstance(response_json, dict):
                    error_type = response_json.get("errorType")
                    error_msg = response_json.get("errorMessage", "")
                    
                    if error_type == "RATE_LIMIT_ERROR" or "too many requests" in error_msg.lower():
                        retries += 1
                        if retries > max_retries:
                            logger.error(f"Max retries ({max_retries}) exceeded for rate limit. Response: {response_json}")
                            return response_json
                            
                        logger.warning(
                            f"API Rate limit hit ({error_type}). Retrying {retries}/{max_retries} in {backoff:.2f}s... "
                            f"Error: {error_msg}"
                        )
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                
                return response_json
                
            except requests.exceptions.RequestException as e:
                retries += 1
                if retries > max_retries:
                    logger.error(f"Request exception. Max retries ({max_retries}) exceeded: {e}")
                    raise e
                logger.warning(f"Request failed: {e}. Retrying {retries}/{max_retries} in {backoff:.2f}s...")
                time.sleep(backoff)
                backoff *= 2
                
        raise RuntimeError("Retries exhausted without return or raising error.")

    def get_historical_daily(self, security_id, exchange_segment, instrument_type, from_date, to_date):
        """Get daily historical OHLCV candles."""
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument_type,
            "fromDate": from_date,
            "toDate": to_date
        }
        return self._post_request("/charts/historical", payload)

    def get_historical_intraday(self, security_id, exchange_segment, instrument_type, from_date, to_date, interval="1"):
        """Get intraday historical OHLCV candles (1-min, 5-min, etc.)."""
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument_type,
            "fromDate": from_date,
            "toDate": to_date,
            "interval": str(interval)
        }
        return self._post_request("/charts/intraday", payload)

    def get_rolling_option(self, security_id, exchange_segment, instrument_type, expiry_flag, expiry_code, strike, option_type, from_date, to_date, interval="1"):
        """Get rolling options historical OHLCV, OI, and IV candles (for expired contracts)."""
        payload = {
            "exchangeSegment": exchange_segment,
            "interval": str(interval),
            "securityId": str(security_id),
            "instrument": instrument_type,
            "expiryFlag": expiry_flag,
            "expiryCode": int(expiry_code),
            "strike": strike,
            "drvOptionType": option_type,
            "requiredData": ["open", "high", "low", "close", "volume", "oi", "iv", "spot"],
            "fromDate": from_date,
            "toDate": to_date
        }
        return self._post_request("/charts/rollingoption", payload)

