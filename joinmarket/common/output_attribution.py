from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass

class Role(Enum):
    TAKER = "taker"
    MAKER = "maker"
    UNKNOWN = "unknown"


@dataclass
class OutputAttribution:
    """Attribution info for an output."""
    attributed_role: Role = Role.UNKNOWN
    role_probability: float = 0.0

    attributed_identity: Optional[str] = None
    identity_confidence: float = 0.0

    def set_identity(self, identity: str, confidence: float):
        self.attributed_identity = identity
        self.identity_confidence = confidence
        # If we know the identity, we know it's a taker
        self.attributed_role = Role.TAKER
        self.role_probability = confidence
