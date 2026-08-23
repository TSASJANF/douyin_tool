"""Pydantic data models for Douyin Link Resolver."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CommentUser(BaseModel):
    """Minimal user info for comments (privacy-safe)."""

    nickname: str = Field(description="Public display name")


class Comment(BaseModel):
    """A single comment on a Douyin work."""

    cid: str = Field(description="Comment ID")
    text: str = Field(description="Comment text content")
    like_count: int = Field(default=0, description="Number of likes")
    reply_count: Optional[int] = Field(default=None, description="Number of replies")
    create_time: Optional[str] = Field(default=None, description="Comment creation time")


class Author(BaseModel):
    """Author of a Douyin work."""

    nickname: str = Field(description="Author display name")
    sec_uid: Optional[str] = Field(default=None, description="Author sec_uid")


class VideoQuality(BaseModel):
    """Video quality option."""

    quality_name: str = Field(description="Quality label (e.g. 480p, 720p, 1080p)")
    bit_rate: int = Field(default=0, description="Bit rate in bps")
    url: str = Field(description="Video download URL")
    mime: Optional[str] = Field(default="video/mp4", description="MIME type")


class MusicInfo(BaseModel):
    """Background music information."""

    title: Optional[str] = Field(default=None, description="Music title")
    author: Optional[str] = Field(default=None, description="Music author")
    url: Optional[str] = Field(default=None, description="Music download URL")
    duration: Optional[int] = Field(default=None, description="Music duration in seconds")
    mid: Optional[str] = Field(default=None, description="Music ID for fetching URL")


class ImageItem(BaseModel):
    """A single image or video in a 图文 post."""

    type: Literal["image", "video"] = Field(description="Item type")
    url: str = Field(description="Default download URL")
    mime: Optional[str] = Field(default=None, description="MIME type")
    urls: dict = Field(default_factory=dict, description="URLs by format: {'webp': url, 'jpeg': url}")


class Media(BaseModel):
    """Video media information."""

    type: Literal["video", "图文"] = Field(default="video", description="Media type")
    downloadable: bool = Field(default=False, description="Whether the video is downloadable")
    url: Optional[str] = Field(default=None, description="Direct video URL")
    mime: Optional[str] = Field(default=None, description="MIME type (e.g. video/mp4)")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes if known")
    expires_at: Optional[str] = Field(default=None, description="URL expiration time if known")
    reason_if_unavailable: Optional[str] = Field(
        default=None, description="Reason why video is not available"
    )
    qualities: list[VideoQuality] = Field(default_factory=list, description="Available quality options")
    images: list[ImageItem] = Field(default_factory=list, description="Images for 图文 posts")
    music: Optional[MusicInfo] = Field(default=None, description="Background music info")


class ErrorInfo(BaseModel):
    """Structured error information."""

    code: str = Field(description="Error code")
    message: str = Field(description="Human-readable error message")
    detail: Optional[str] = Field(default=None, description="Additional detail")


class ResolveResult(BaseModel):
    """Complete result of resolving a Douyin link."""

    ok: bool = Field(description="Whether the resolution succeeded")
    platform: Literal["douyin"] = Field(default="douyin")
    input_url: str = Field(description="Original input URL")
    resolved_url: Optional[str] = Field(default=None, description="Final resolved URL after redirects")
    aweme_id: Optional[str] = Field(default=None, description="Douyin work ID")
    title: Optional[str] = Field(default=None, description="Work title")
    author: Optional[Author] = Field(default=None)
    cover_url: Optional[str] = Field(default=None, description="Cover image URL")
    media: Optional[Media] = Field(default=None)
    comments: list[Comment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: Optional[ErrorInfo] = Field(default=None)
    create_time: Optional[int] = Field(default=None, description="Publish timestamp")
    digg_count: Optional[int] = Field(default=None, description="Like count")
    comment_count: Optional[int] = Field(default=None, description="Comment count")
    share_count: Optional[int] = Field(default=None, description="Share count")
    play_count: Optional[int] = Field(default=None, description="Play count")
