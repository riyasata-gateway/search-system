from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class RawMention:
    source_type: str
    source_url: Optional[str]
    country: Optional[str]
    language: Optional[str]
    published_at: Optional[datetime]
    raw_text: str
    query_used: str
    author_id: Optional[str] = None
    engagement_count: Optional[int] = None
    metadata: dict = field(default_factory=dict)


class BaseConnector(ABC):
    source_type: str = ""

    @abstractmethod
    async def collect(self, keywords: List[str], countries: List[str], languages: List[str]) -> List[RawMention]:
        """Collect raw mentions for the given keywords, countries, and languages."""
        ...

    def is_available(self) -> bool:
        """Return False if required credentials are missing."""
        return True
