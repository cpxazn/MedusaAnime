# coding=utf-8
"""Anime lookup clients package."""
from __future__ import unicode_literals

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class AnimeSeason:
    """Represents a season of an anime."""
    season: str  # SPRING, SUMMER, FALL, WINTER
    year: int
    title: str


@dataclass
class AnimeSeries:
    """Represents an anime series with metadata."""
    # Identifier
    anime_id: int  # Source-specific ID
    source: str  # 'livechart', 'myanimelist'
    
    # Titles
    title_japanese: Optional[str] = None  # Japanese title (e.g., \u6771\u4eac\u30ea\u30d9\u30f3\u30b8\u30e3\u30fc\u30ba)
    title_romanji: Optional[str] = None  # Romanji title (e.g., Tokyo Revengers)
    title_english: Optional[str] = None  # English title (e.g., Tokyo Revengers)
    title_synonyms: List[str] = field(default_factory=list)  # Alternative titles
    
    # Metadata
    synopsis: Optional[str] = None
    anime_type: str = 'TV'  # TV, OVA, Movie, Special, ONA, OND
    status: str = 'upcoming'  # airing, finished, upcoming, cancelled
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None  # YYYY-MM-DD
    season: Optional[str] = None  # SPRING, SUMMER, FALL, WINTER
    year: Optional[int] = None
    episodes: Optional[int] = None
    episode_duration_minutes: Optional[int] = None
    episode_info: Optional[str] = None  # Raw display text, e.g. "12 eps × 24m"
    score: Optional[float] = None
    rating: Optional[float] = None
    genres: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    studios: List[str] = field(default_factory=list)
    next_episode_number: Optional[int] = None
    next_episode_release: Optional[str] = None  # Localized date text from source
    next_episode_countdown: Optional[str] = None  # e.g. "0d 06h 01m 03s"
    
    # Images
    image_url: Optional[str] = None
    banner_url: Optional[str] = None
    
    # Cross-references
    anidb_id: Optional[int] = None
    anilist_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    mal_id: Optional[int] = None  # MyAnimeList ID (also used as anime_id for MAL source)
    
    # Relationships
    seasons: List[AnimeSeason] = field(default_factory=list)
    prequels: List['AnimeSeries'] = field(default_factory=list)
    sequels: List['AnimeSeries'] = field(default_factory=list)
    
    # URL
    url: Optional[str] = None
    
    @property
    def start_year(self) -> Optional[int]:
        """Get the start year from start_date or year."""
        return self.year
    
    @property
    def display_title(self) -> str:
        """Get the primary display title."""
        if self.title_english:
            return self.title_english
        if self.title_romanji:
            return self.title_romanji
        if self.title_japanese:
            return self.title_japanese
        return f"Unknown Anime ({self.anime_id})"
    
    @property
    def directory_name(self) -> str:
        """Get a filesystem-safe directory name."""
        import re
        import unicodedata
        
        # Use romanji or english for directory name
        name = self.title_romanji or self.title_english or self.title_japanese or f"anime_{self.anime_id}"
        
        # Normalize unicode
        name = unicodedata.normalize('NFKC', name)
        
        # Remove invalid filesystem characters
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        
        # Collapse whitespace
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Append year
        if self.year:
            name = f"{name} ({self.year})"
        
        return name


class AnimeSource(ABC):
    """Abstract base class for anime lookup sources."""
    
    BASE_URL: str = ''
    RATE_LIMIT: int = 10  # requests per second
    
    @abstractmethod
    def search(self, query: str) -> List[AnimeSeries]:
        """Search for anime by title.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching AnimeSeries objects
        """
        pass
    
    @abstractmethod
    def get_seasonal(self, year: int, season: str) -> List[AnimeSeries]:
        """Get seasonal anime for a given year/season.
        
        Args:
            year: Year (e.g., 2026)
            season: Season (SPRING, SUMMER, FALL, WINTER)
            
        Returns:
            List of AnimeSeries for the season
        """
        pass
    
    @abstractmethod
    def get_details(self, anime_id: int) -> AnimeSeries:
        """Get detailed information for a specific anime.
        
        Args:
            anime_id: Source-specific anime ID
            
        Returns:
            AnimeSeries object with full details
        """
        pass
    
    @abstractmethod
    def get_upcoming(self, limit: int = 20) -> List[AnimeSeries]:
        """Get upcoming anime releases.
        
        Args:
            limit: Maximum number of results to return
            
        Returns:
            List of upcoming AnimeSeries objects
        """
        pass

