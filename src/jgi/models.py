from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PostMeta(BaseModel):
    no: int = Field(..., description="게시글 번호")
    category: str = Field("", description="말머리 (일반/뉴스/공지/AD 등)")
    title: str
    author: str = ""
    posted_at: datetime
    views: int = 0
    recommends: int = 0
    comments: int = 0
    url: str

    @property
    def score(self) -> float:
        return float(self.views) + float(self.recommends) * 3.0


class Post(PostMeta):
    body: str = ""


class TopTicker(BaseModel):
    ticker: str
    mentions: int
    sentiment: str = Field(..., description="bullish | bearish | neutral | mixed")


class NotableQuote(BaseModel):
    quote: str
    title: str = ""
    views: int = 0
    recommends: int = 0


class AnalysisResult(BaseModel):
    overall_sentiment: str = Field(..., description="bullish | bearish | neutral | mixed")
    sentiment_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="bullish/bearish/neutral 비율, 합 ~= 1.0",
    )
    hot_tickers: list[TopTicker] = Field(default_factory=list)
    key_themes: list[str] = Field(default_factory=list)
    notable_quotes: list[NotableQuote] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    summary: str = ""
