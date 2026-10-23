from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class DeviceEvent:
    credential_ref: str
    event_type: str
    payload: dict
    created_at: str

    @classmethod
    def create(cls, credential_ref, event_type, payload):
        return cls(
            credential_ref,
            event_type,
            payload,
            datetime.now(timezone.utc).isoformat(),
        )
