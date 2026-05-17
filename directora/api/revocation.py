"""JWT revocation store — jti blacklist with TTL-based cleanup."""
import time
import threading
from typing import Set

class JWTRevocationStore:
    """
    In-memory jti revocation store with periodic cleanup.
    
    Production swap: replace with Redis SET with TTL.
    Same interface: is_revoked(jti) -> bool, revoke(jti) -> None
    """
    
    def __init__(self, cleanup_interval: int = 300):
        self._revoked: Set[str] = set()
        self._expiry: dict[str, float] = {}  # jti -> epoch when token would have expired
        self._lock = threading.Lock()
        self._cleanup_interval = cleanup_interval
        self._start_cleanup()
    
    def revoke(self, jti: str, token_exp: float):
        """Add jti to revocation store. token_exp is the JWT exp claim as epoch."""
        with self._lock:
            self._revoked.add(jti)
            self._expiry[jti] = token_exp
    
    def is_revoked(self, jti: str) -> bool:
        """Check if jti has been revoked."""
        with self._lock:
            return jti in self._revoked
    
    def _cleanup_expired(self):
        """Remove entries for tokens that have expired anyway."""
        now = time.time()
        with self._lock:
            expired = [jti for jti, exp in self._expiry.items() if exp < now]
            for jti in expired:
                self._revoked.discard(jti)
                del self._expiry[jti]
    
    def _start_cleanup(self):
        """Periodic cleanup of expired entries."""
        def cleanup_loop():
            while True:
                time.sleep(self._cleanup_interval)
                self._cleanup_expired()
        
        thread = threading.Thread(target=cleanup_loop, daemon=True)
        thread.start()


# Singleton
_revocation_store: JWTRevocationStore | None = None

def get_revocation_store() -> JWTRevocationStore:
    global _revocation_store
    if _revocation_store is None:
        _revocation_store = JWTRevocationStore()
<<<<<<< Updated upstream
    return _revocation_store
=======
    return _revocation_store
>>>>>>> Stashed changes
