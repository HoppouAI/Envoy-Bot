"""
Discord Architect Module for Envoy Bot.

This module contains the DiscordArchitect class that provides Discord API
operations as tools for the Copilot SDK. Each tool is designed to perform
specific server configuration tasks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import discord
from discord import (
    CategoryChannel,
    Guild,
    HTTPException,
    Forbidden,
    PermissionOverwrite,
    Role,
    TextChannel,
    VoiceChannel,
)
from pydantic import BaseModel, Field

logger = logging.getLogger("envoy.architect")


class ChannelType(str, Enum):
    """Supported Discord channel types."""
    TEXT = "text"
    VOICE = "voice"
    CATEGORY = "category"


class PermissionValue(str, Enum):
    """Permission override values."""
    ALLOW = "allow"
    DENY = "deny"
    NEUTRAL = "neutral"


# ============================================================================
# Pydantic Models for Tool Parameters
# ============================================================================


class CreateChannelParams(BaseModel):
    """Parameters for creating a Discord channel."""
    name: str = Field(description="Name of the channel to create")
    channel_type: str = Field(
        default="text",
        description="Type of channel: 'text', 'voice', or 'category'"
    )
    category_name: Optional[str] = Field(
        default=None,
        description="Name of the category to place the channel in (optional)"
    )
    topic: Optional[str] = Field(
        default=None,
        description="Channel topic/description (text channels only)"
    )
    slowmode_delay: Optional[int] = Field(
        default=None,
        description="Slowmode delay in seconds (0-21600, text channels only)"
    )
    nsfw: bool = Field(
        default=False,
        description="Whether the channel is NSFW"
    )
    position: Optional[int] = Field(
        default=None,
        description="Position of the channel in the channel list"
    )
    private: bool = Field(
        default=False,
        description="If true, hide channel from @everyone by default"
    )
    allowed_roles: Optional[list[str]] = Field(
        default=None,
        description="List of role names that can access this channel (requires private=true)"
    )
    denied_roles: Optional[list[str]] = Field(
        default=None,
        description="List of role names that cannot access this channel"
    )
    sync_permissions: bool = Field(
        default=True,
        description="Whether to sync permissions with the parent category"
    )


class CreateRoleParams(BaseModel):
    """Parameters for creating a Discord role."""
    name: str = Field(description="Name of the role to create")
    color: Optional[str] = Field(
        default=None,
        description="Hex color code (e.g., '#FF5733' or 'FF5733')"
    )
    hoist: bool = Field(
        default=False,
        description="Whether to display role members separately"
    )
    mentionable: bool = Field(
        default=False,
        description="Whether the role can be mentioned"
    )
    permissions: Optional[list[str]] = Field(
        default=None,
        description="List of permission names to grant (e.g., ['send_messages', 'read_messages'])"
    )


class SetPermissionsParams(BaseModel):
    """Parameters for setting channel permissions."""
    channel_name: str = Field(description="Name of the channel to modify")
    target_name: str = Field(description="Name of the role or member to set permissions for")
    target_type: str = Field(
        default="role",
        description="Type of target: 'role' or 'member'"
    )
    permissions: dict[str, str] = Field(
        description="Dict of permission names to values ('allow', 'deny', 'neutral')"
    )


class CreateCategoryParams(BaseModel):
    """Parameters for creating a category with channels."""
    name: str = Field(description="Name of the category to create")
    channels: Optional[list[dict]] = Field(
        default=None,
        description="List of channel configs: [{'name': 'general', 'type': 'text', 'topic': 'desc'}]"
    )
    position: Optional[int] = Field(
        default=None,
        description="Position of the category in the channel list"
    )
    private: bool = Field(
        default=False,
        description="If true, hide category from @everyone by default"
    )
    allowed_roles: Optional[list[str]] = Field(
        default=None,
        description="List of role names that can access this category and its channels"
    )
    denied_roles: Optional[list[str]] = Field(
        default=None,
        description="List of role names that cannot access this category"
    )


class ModifyServerSettingsParams(BaseModel):
    """Parameters for modifying server settings."""
    name: Optional[str] = Field(
        default=None,
        description="New server name"
    )
    icon_url: Optional[str] = Field(
        default=None,
        description="URL to image for server icon/logo. Must be a direct image URL (png, jpg, gif). Image will be downloaded and set as server icon."
    )
    banner_url: Optional[str] = Field(
        default=None,
        description="URL to image for server banner. Requires server boost level 2+. Must be a direct image URL (png, jpg, gif)."
    )
    verification_level: Optional[str] = Field(
        default=None,
        description="Verification level: 'none', 'low', 'medium', 'high', 'highest'"
    )
    default_notifications: Optional[str] = Field(
        default=None,
        description="Default notifications: 'all_messages' or 'only_mentions'"
    )
    afk_channel: Optional[str] = Field(
        default=None,
        description="Name of the AFK voice channel"
    )
    afk_timeout: Optional[int] = Field(
        default=None,
        description="AFK timeout in seconds (60, 300, 900, 1800, 3600)"
    )
    system_channel: Optional[str] = Field(
        default=None,
        description="Name of the system messages channel"
    )


class DeleteChannelParams(BaseModel):
    """Parameters for deleting a channel."""
    name: str = Field(description="Name of the channel to delete")
    reason: Optional[str] = Field(
        default=None,
        description="Reason for deletion (audit log)"
    )


class DeleteRoleParams(BaseModel):
    """Parameters for deleting a role."""
    name: str = Field(description="Name of the role to delete")
    reason: Optional[str] = Field(
        default=None,
        description="Reason for deletion (audit log)"
    )


class DeleteCategoryParams(BaseModel):
    """Parameters for deleting a category."""
    name: str = Field(description="Name of the category to delete")
    reason: Optional[str] = Field(
        default=None,
        description="Reason for deletion (audit log)"
    )
    delete_channels: bool = Field(
        default=True,
        description="Whether to also delete all channels inside the category"
    )


class EditCategoryParams(BaseModel):
    """Parameters for editing an existing category."""
    name: str = Field(description="Current name of the category to edit")
    new_name: Optional[str] = Field(
        default=None,
        description="New name for the category"
    )
    position: Optional[int] = Field(
        default=None,
        description="New position for the category"
    )


class SetCategoryPermissionsParams(BaseModel):
    """Parameters for setting category-wide permissions."""
    category_name: str = Field(description="Name of the category to modify")
    role_permissions: dict[str, dict[str, str]] = Field(
        description="Dict mapping role names to their permissions: {'Staff': {'view_channel': 'allow', 'send_messages': 'allow'}}"
    )
    sync_to_channels: bool = Field(
        default=True,
        description="Whether to sync these permissions to all channels in the category"
    )


class MakeChannelPrivateParams(BaseModel):
    """Parameters for making a channel private to specific roles."""
    channel_name: str = Field(description="Name of the channel to make private")
    allowed_roles: list[str] = Field(
        description="List of role names that can access this channel"
    )
    deny_everyone: bool = Field(
        default=True,
        description="Whether to deny @everyone access"
    )


class MoveChannelParams(BaseModel):
    """Parameters for moving a channel to a category."""
    channel_name: str = Field(description="Name of the channel to move")
    category_name: Optional[str] = Field(
        default=None,
        description="Name of the category to move to (None to remove from category)"
    )
    sync_permissions: bool = Field(
        default=True,
        description="Whether to sync permissions with the new category"
    )
    position: Optional[int] = Field(
        default=None,
        description="New position within the category"
    )


class EditChannelParams(BaseModel):
    """Parameters for editing an existing channel."""
    name: str = Field(description="Current name of the channel to edit")
    new_name: Optional[str] = Field(
        default=None,
        description="New name for the channel"
    )
    topic: Optional[str] = Field(
        default=None,
        description="New topic/description (text channels only)"
    )
    slowmode_delay: Optional[int] = Field(
        default=None,
        description="New slowmode delay in seconds"
    )
    nsfw: Optional[bool] = Field(
        default=None,
        description="Whether the channel is NSFW"
    )
    position: Optional[int] = Field(
        default=None,
        description="New position"
    )


class EditRoleParams(BaseModel):
    """Parameters for editing an existing role."""
    name: str = Field(description="Current name of the role to edit")
    new_name: Optional[str] = Field(
        default=None,
        description="New name for the role"
    )
    color: Optional[str] = Field(
        default=None,
        description="New hex color code"
    )
    hoist: Optional[bool] = Field(
        default=None,
        description="Whether to display role members separately"
    )
    mentionable: Optional[bool] = Field(
        default=None,
        description="Whether the role can be mentioned"
    )
    permissions: Optional[list[str]] = Field(
        default=None,
        description="New list of permission names (replaces existing)"
    )
    position: Optional[int] = Field(
        default=None,
        description="New position in role hierarchy"
    )


class AssignRoleParams(BaseModel):
    """Parameters for assigning a role to a member."""
    member_name: str = Field(
        description="Username or display name of the member"
    )
    role_name: str = Field(description="Name of the role to assign")
    reason: Optional[str] = Field(
        default=None,
        description="Reason for assignment (audit log)"
    )


class RemoveRoleParams(BaseModel):
    """Parameters for removing a role from a member."""
    member_name: str = Field(
        description="Username or display name of the member"
    )
    role_name: str = Field(description="Name of the role to remove")
    reason: Optional[str] = Field(
        default=None,
        description="Reason for removal (audit log)"
    )


class BulkCreateRolesParams(BaseModel):
    """Parameters for creating multiple roles at once."""
    roles: list[dict] = Field(
        description="List of role configs: [{'name': 'Admin', 'color': '#FF0000', 'permissions': ['administrator']}]"
    )


class CloneChannelPermissionsParams(BaseModel):
    """Parameters for cloning permissions from one channel to another."""
    source_channel: str = Field(description="Name of the channel to copy permissions from")
    target_channel: str = Field(description="Name of the channel to copy permissions to")


class UpdateProgressParams(BaseModel):
    """Parameters for updating the progress tracker."""
    task_id: int = Field(description="Unique ID for this task (1-based)")
    task_name: str = Field(description="Short name for the task (e.g., 'Create Admin role')")
    status: str = Field(
        description="Status: 'pending', 'in_progress', 'completed', 'failed'"
    )
    details: Optional[str] = Field(
        default=None,
        description="Additional details or error message"
    )


class SetPlanParams(BaseModel):
    """Parameters for setting the execution plan."""
    plan_title: str = Field(description="Title for the plan (e.g., 'Gaming Server Setup')")
    tasks: list[str] = Field(
        description="List of task names in order (e.g., ['Create roles', 'Create categories', 'Set permissions'])"
    )


class AskUserParams(BaseModel):
    """Parameters for asking the user a question mid-task."""
    question: str = Field(
        description="The question to ask the user. Be specific and clear about what you need to know."
    )
    context: Optional[str] = Field(
        default=None,
        description="Additional context about why you're asking (e.g., 'I need to know this to set up permissions correctly')"
    )
    options: Optional[list[str]] = Field(
        default=None,
        description="Optional list of suggested answers the user can choose from"
    )


class MarkCompleteParams(BaseModel):
    """Parameters for marking a task as complete."""
    summary: str = Field(
        description="Brief summary of what was accomplished (e.g., 'Changed server name to Gaming Hub' or 'Deleted 3 channels and 2 roles')"
    )
    details: Optional[str] = Field(
        default=None,
        description="Optional detailed explanation of what was done"
    )


class GetDesignSectionParams(BaseModel):
    """Parameters for getting a design documentation section."""
    section: str = Field(
        description="Section name to retrieve: 'Script Fonts', 'Gothic Fonts', 'Sans-Serif Fonts', 'Serif Fonts', 'Special Fonts', 'Separators', 'Decorative Elements', 'Category Patterns', 'Channel Patterns', 'Gaming Template', 'Professional Template', 'Tech Template', 'Aesthetic Template', 'Kawaii Template', 'Emoji Guidelines', 'Color Palettes', 'Description Formats', 'Best Practices', 'Templates', or 'All' for entire guide"
    )


class CreateWebhookParams(BaseModel):
    """Parameters for creating a webhook in a channel."""
    channel_name: str = Field(description="Name of the channel to create webhook in")
    webhook_name: str = Field(
        default="Envoy",
        description="Name for the webhook (appears as the sender name)"
    )
    avatar_url: Optional[str] = Field(
        default=None,
        description="URL for the webhook's avatar image"
    )


class PostWebhookEmbedParams(BaseModel):
    """Parameters for posting an embed message via webhook."""
    channel_name: str = Field(description="Name of the channel to post in")
    title: str = Field(description="Title of the embed")
    description: str = Field(description="Main content/description of the embed")
    color: Optional[str] = Field(
        default=None,
        description="Hex color code for the embed (e.g., '#FF5733')"
    )
    fields: Optional[list[dict]] = Field(
        default=None,
        description="List of fields: [{'name': 'Field Name', 'value': 'Field content', 'inline': True}]"
    )
    footer: Optional[str] = Field(
        default=None,
        description="Footer text for the embed"
    )
    image_url: Optional[str] = Field(
        default=None,
        description="URL of an image to include in the embed"
    )
    thumbnail_url: Optional[str] = Field(
        default=None,
        description="URL of a thumbnail image for the embed"
    )
    webhook_name: Optional[str] = Field(
        default="Envoy",
        description="Name to display as the sender"
    )
    webhook_avatar: Optional[str] = Field(
        default=None,
        description="Avatar URL for the webhook sender"
    )


class GetWebhookParams(BaseModel):
    """Parameters for getting a webhook URL for a channel."""
    channel_name: str = Field(description="Name of the channel to get/create webhook for")


class EditWebhookMessageParams(BaseModel):
    """Parameters for editing an existing webhook message."""
    channel_name: str = Field(description="Name of the channel containing the message")
    message_id: int = Field(description="ID of the message to edit (from previous post_embed response)")
    title: Optional[str] = Field(default=None, description="New title for the embed")
    description: Optional[str] = Field(default=None, description="New description for the embed")
    color: Optional[str] = Field(default=None, description="New color as hex (e.g., '#3498db')")
    fields: Optional[list[dict]] = Field(
        default=None,
        description="New fields for the embed - replaces all existing fields"
    )
    footer: Optional[str] = Field(default=None, description="New footer text")
    image_url: Optional[str] = Field(default=None, description="New image URL")
    thumbnail_url: Optional[str] = Field(default=None, description="New thumbnail URL")


class DeleteWebhookMessageParams(BaseModel):
    """Parameters for deleting a webhook message."""
    channel_name: str = Field(description="Name of the channel containing the message")
    message_id: int = Field(description="ID of the message to delete")


class ListWebhookMessagesParams(BaseModel):
    """Parameters for listing recent messages from Envoy webhook in a channel."""
    channel_name: str = Field(description="Name of the channel to search")
    limit: int = Field(default=10, description="Maximum number of messages to return (1-50)")


class AutoConfigurePermissionsParams(BaseModel):
    """Parameters for automatically configuring server permissions based on a template.
    
    This tool acts as a sub-agent that handles all permission configuration in one call,
    applying professional permission templates to categories and channels.
    """
    template: str = Field(
        description="Permission template to apply: 'professional' (read-only info, member-only chat, staff-private), 'community' (open with moderation), 'private' (invite-only), or 'gaming' (voice-focused)"
    )
    staff_roles: list[str] = Field(
        default_factory=list,
        description="Role names that should have staff/moderator access (e.g., ['Admin', 'Mod', 'Staff'])"
    )
    member_role: Optional[str] = Field(
        default=None,
        description="Role name for verified members (if None, uses @everyone for non-private categories)"
    )
    info_categories: list[str] = Field(
        default_factory=list,
        description="Category names that should be read-only for members (e.g., ['INFORMATION', 'RULES'])"
    )
    staff_categories: list[str] = Field(
        default_factory=list,
        description="Category names that should be staff-only (e.g., ['STAFF', 'ADMIN'])"
    )
    announcement_channels: list[str] = Field(
        default_factory=list,
        description="Channel names that should be read-only (e.g., ['announcements', 'rules'])"
    )


# ============================================================================
# Progress Tracker Class
# ============================================================================


class ProgressTracker:
    """
    Tracks execution progress and updates a Discord embed message.
    
    This class manages a live-updating embed in the summary channel
    that shows the current status of all tasks.
    """

    STATUS_EMOJI = {
        "pending": "⏳",
        "in_progress": "🔄",
        "completed": "✅",
        "failed": "❌",
    }

    def __init__(self):
        """Initialize the progress tracker."""
        self.plan_title: str = "Server Configuration"
        self.tasks: list[dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.message: Optional[discord.Message] = None
        self.channel: Optional[discord.TextChannel] = None
        self._lock = asyncio.Lock()

    def set_channel(self, channel: discord.TextChannel) -> None:
        """Set the summary channel for progress updates."""
        self.channel = channel

    def set_message(self, message: discord.Message) -> None:
        """Set the message to edit for progress updates."""
        self.message = message

    def set_plan(self, title: str, task_names: list[str]) -> None:
        """
        Set up the execution plan with tasks.
        
        Args:
            title: Title for the plan.
            task_names: List of task names in execution order.
        """
        self.plan_title = title
        self.tasks = [
            {
                "id": i + 1,
                "name": name,
                "status": "pending",
                "details": None,
            }
            for i, name in enumerate(task_names)
        ]
        self.start_time = asyncio.get_event_loop().time()

    def update_task(
        self,
        task_id: int,
        status: str,
        details: Optional[str] = None,
    ) -> None:
        """
        Update a task's status.
        
        Args:
            task_id: The task ID (1-based).
            status: New status ('pending', 'in_progress', 'completed', 'failed').
            details: Optional details or error message.
        """
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = status
                task["details"] = details
                break

    def add_task(self, name: str, status: str = "pending") -> int:
        """
        Add a new task dynamically.
        
        Args:
            name: Task name.
            status: Initial status.
            
        Returns:
            The new task's ID.
        """
        task_id = len(self.tasks) + 1
        self.tasks.append({
            "id": task_id,
            "name": name,
            "status": status,
            "details": None,
        })
        return task_id

    def build_embed(self) -> discord.Embed:
        """Build the progress embed."""
        # Calculate stats
        completed = sum(1 for t in self.tasks if t["status"] == "completed")
        failed = sum(1 for t in self.tasks if t["status"] == "failed")
        in_progress = sum(1 for t in self.tasks if t["status"] == "in_progress")
        total = len(self.tasks)

        # Determine overall status color
        if failed > 0:
            color = discord.Color.orange()
        elif completed == total and total > 0:
            color = discord.Color.green()
        elif in_progress > 0:
            color = discord.Color.blue()
        else:
            color = discord.Color.greyple()

        embed = discord.Embed(
            title=f"🏗️ {self.plan_title}",
            color=color,
            timestamp=discord.utils.utcnow(),
        )

        # Progress bar
        if total > 0:
            progress_pct = (completed / total) * 100
            filled = int(progress_pct / 5)
            bar = "█" * filled + "░" * (20 - filled)
            embed.description = f"**Progress:** `{bar}` {progress_pct:.0f}%\n\n"
        else:
            embed.description = "Setting up plan...\n\n"

        # Task list
        task_lines = []
        for task in self.tasks:
            emoji = self.STATUS_EMOJI.get(task["status"], "❓")
            line = f"{emoji} **{task['id']}.** {task['name']}"
            if task["details"]:
                line += f"\n   ↳ _{task['details']}_"
            task_lines.append(line)

        if task_lines:
            # Split into chunks if too long
            task_text = "\n".join(task_lines)
            if len(task_text) > 1000:
                task_text = task_text[:1000] + "\n..."
            embed.add_field(
                name="📋 Tasks",
                value=task_text or "No tasks defined",
                inline=False,
            )

        # Stats footer
        elapsed = ""
        if self.start_time:
            elapsed_sec = asyncio.get_event_loop().time() - self.start_time
            elapsed = f" | ⏱️ {elapsed_sec:.1f}s"

        embed.set_footer(
            text=f"✅ {completed}/{total} completed | ❌ {failed} failed{elapsed}"
        )

        return embed

    async def update_message(self) -> None:
        """Update the progress message in Discord."""
        async with self._lock:
            if self.message:
                try:
                    embed = self.build_embed()
                    await self.message.edit(embed=embed)
                except discord.HTTPException as e:
                    logger.warning(f"Failed to update progress message: {e}")

    async def send_initial(self) -> Optional[discord.Message]:
        """Send the initial progress embed."""
        if self.channel:
            try:
                embed = self.build_embed()
                self.message = await self.channel.send(embed=embed)
                return self.message
            except discord.HTTPException as e:
                logger.error(f"Failed to send progress embed: {e}")
        return None

    def reset(self) -> None:
        """Reset the tracker for a new operation."""
        self.tasks = []
        self.message = None
        self.start_time = None
        self.plan_title = "Server Configuration"


# ============================================================================
# Tool Result Classes
# ============================================================================


@dataclass
class ToolResult:
    """Result of a tool operation."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for SDK response."""
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
        }


@dataclass
class PlanAction:
    """A single action in an execution plan."""
    tool_name: str
    description: str
    params: dict[str, Any]
    order: int


@dataclass
class ExecutionPlan:
    """A plan of actions to execute on the server."""
    title: str
    description: str
    actions: list[PlanAction]
    estimated_time: str
    warnings: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Convert plan to Discord-friendly markdown."""
        lines = [
            f"## 📋 Execution Plan: {self.title}",
            "",
            f"**Description:** {self.description}",
            f"**Estimated Time:** {self.estimated_time}",
            f"**Total Actions:** {len(self.actions)}",
            "",
        ]

        if self.warnings:
            lines.append("### ⚠️ Warnings")
            for warning in self.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        lines.append("### 📝 Planned Actions")
        for action in sorted(self.actions, key=lambda a: a.order):
            lines.append(f"{action.order}. **{action.tool_name}**: {action.description}")

        return "\n".join(lines)


# ============================================================================
# Rate Limiter
# ============================================================================


class RateLimiter:
    """
    Conservative rate limiter for Discord API calls.
    
    Implements a soft rate limit to prevent hitting Discord's rate limits:
    - 1 second minimum between channel/category creations
    - Tracks rolling window of API calls
    - Automatically slows down when approaching limits
    """

    def __init__(
        self,
        max_calls_per_minute: int = 25,
        min_delay_seconds: float = 1.0,
        burst_limit: int = 5,
    ):
        """
        Initialize the rate limiter.

        Args:
            max_calls_per_minute: Maximum API calls allowed per minute (conservative).
            min_delay_seconds: Minimum delay between operations in seconds.
            burst_limit: Max operations before enforcing delays.
        """
        self.max_calls_per_minute = max_calls_per_minute
        self.min_delay = min_delay_seconds
        self.burst_limit = burst_limit
        self._call_times: list[float] = []
        self._operation_count = 0
        self._lock = asyncio.Lock()
        self._last_call_time: float = 0

    async def acquire(self) -> None:
        """Wait until an API call is allowed with soft rate limiting."""
        async with self._lock:
            now = asyncio.get_event_loop().time()

            # Always enforce minimum delay between calls
            time_since_last = now - self._last_call_time
            if time_since_last < self.min_delay:
                wait_time = self.min_delay - time_since_last
                logger.debug(f"Soft rate limit: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                now = asyncio.get_event_loop().time()

            # Remove calls older than 1 minute
            self._call_times = [t for t in self._call_times if now - t < 60]

            # If approaching limit, slow down progressively
            call_count = len(self._call_times)
            if call_count >= self.max_calls_per_minute * 0.8:
                # At 80% capacity, add extra delay
                extra_delay = 2.0
                logger.warning(f"Approaching rate limit ({call_count}/{self.max_calls_per_minute}), adding {extra_delay}s delay")
                await asyncio.sleep(extra_delay)
            elif call_count >= self.max_calls_per_minute * 0.5:
                # At 50% capacity, add small delay
                await asyncio.sleep(0.5)

            if call_count >= self.max_calls_per_minute:
                # Wait until the oldest call expires
                wait_time = 60 - (now - self._call_times[0]) + 1.0
                if wait_time > 0:
                    logger.warning(f"Rate limit reached, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)

            self._call_times.append(asyncio.get_event_loop().time())
            self._last_call_time = asyncio.get_event_loop().time()
            self._operation_count += 1

    async def delay_for_creation(self) -> None:
        """Apply delay specifically for channel/category creation (1 second)."""
        await asyncio.sleep(self.min_delay)

    async def batch_delay(self) -> None:
        """Apply delay between batch operations."""
        await asyncio.sleep(self.min_delay)

    def reset_operation_count(self) -> None:
        """Reset the operation counter."""
        self._operation_count = 0

    @property
    def operations_performed(self) -> int:
        """Get number of operations performed."""
        return self._operation_count


# ============================================================================
# Discord Architect Class
# ============================================================================


class DiscordArchitect:
    """
    Discord server architect that provides tools for server configuration.

    This class wraps Discord API operations as tools that can be called by
    the Copilot SDK to autonomously configure Discord servers.
    """

    # Valid Discord permission names
    VALID_PERMISSIONS = {
        "add_reactions", "administrator", "attach_files", "ban_members",
        "change_nickname", "connect", "create_instant_invite",
        "create_private_threads", "create_public_threads", "deafen_members",
        "embed_links", "external_emojis", "external_stickers", "kick_members",
        "manage_channels", "manage_emojis", "manage_emojis_and_stickers",
        "manage_events", "manage_guild", "manage_messages", "manage_nicknames",
        "manage_permissions", "manage_roles", "manage_threads",
        "manage_webhooks", "mention_everyone", "moderate_members",
        "move_members", "mute_members", "priority_speaker", "read_message_history",
        "read_messages", "request_to_speak", "send_messages",
        "send_messages_in_threads", "send_tts_messages", "speak", "stream",
        "use_application_commands", "use_embedded_activities",
        "use_external_emojis", "use_external_stickers", "use_voice_activation",
        "view_audit_log", "view_channel", "view_guild_insights",
    }

    def __init__(
        self,
        guild: Guild,
        rate_limiter: Optional[RateLimiter] = None,
        allow_unsafe_role_ops: bool = False,
    ):
        """
        Initialize the Discord Architect.

        Args:
            guild: The Discord guild to operate on.
            rate_limiter: Optional rate limiter for API calls.
            allow_unsafe_role_ops: Allow operations on roles above bot's role.
        """
        self.guild = guild
        self.rate_limiter = rate_limiter or RateLimiter()
        self.allow_unsafe_role_ops = allow_unsafe_role_ops
        self._execution_log: list[tuple[str, bool]] = []
        self.progress_tracker = ProgressTracker()
        self._created_channels: dict[str, discord.abc.GuildChannel] = {}
        self._created_roles: dict[str, Role] = {}
        self._pending_question: Optional[dict[str, Any]] = None
        self._question_event = asyncio.Event()
        self._question_answer: Optional[str] = None
        self._answer_event = asyncio.Event()

    @property
    def bot_member(self) -> Optional[discord.Member]:
        """Get the bot's member object in the guild."""
        return self.guild.me

    @property
    def bot_top_role(self) -> Optional[Role]:
        """Get the bot's highest role in the guild."""
        if self.bot_member:
            return self.bot_member.top_role
        return None

    def _log_action(self, message: str, success: bool = True) -> None:
        """Log an action for tracking."""
        logger.info(f"[{'SUCCESS' if success else 'FAILED'}] {message}")
        self._execution_log.append((message, success))

    def get_execution_log(self) -> list[tuple[str, bool]]:
        """Get the execution log and clear it."""
        log = self._execution_log.copy()
        self._execution_log.clear()
        self.clear_session_cache()
        return log
    
    def clear_session_cache(self) -> None:
        """Clear the session cache of created objects. Call after each execution."""
        self._created_channels.clear()
        self._created_roles.clear()

    def _check_permissions(self, *required: str) -> tuple[bool, str]:
        """
        Check if the bot has the required permissions.

        Args:
            required: Permission names to check.

        Returns:
            Tuple of (has_permissions, error_message).
        """
        if not self.bot_member:
            return False, "Bot member not found in guild"

        permissions = self.bot_member.guild_permissions

        missing = []
        for perm in required:
            if not getattr(permissions, perm, False):
                missing.append(perm)

        if missing:
            return False, f"Missing permissions: {', '.join(missing)}"

        return True, ""

    def _can_manage_role(self, role: Role) -> bool:
        """Check if the bot can manage a specific role."""
        if self.allow_unsafe_role_ops:
            return True

        if not self.bot_top_role:
            return False

        return self.bot_top_role.position > role.position

    def _parse_color(self, color_str: Optional[str]) -> Optional[discord.Color]:
        """Parse a hex color string to discord.Color."""
        if not color_str:
            return None

        # Remove '#' if present
        color_str = color_str.lstrip('#')

        try:
            return discord.Color(int(color_str, 16))
        except ValueError:
            return None

    def _find_channel_by_name(
        self,
        name: str,
        channel_type: Optional[type] = None,
    ) -> Optional[discord.abc.GuildChannel]:
        """Find a channel by name, optionally filtering by type."""
        name_lower = name.lower()
        logger.debug(f"_find_channel_by_name: searching for '{name}' (type={channel_type})")
        
        # First check session cache (for recently created channels not yet in guild cache)
        if name_lower in self._created_channels:
            cached = self._created_channels[name_lower]
            if channel_type is None or isinstance(cached, channel_type):
                logger.debug(f"_find_channel_by_name: found in session cache '{cached.name}' (ID: {cached.id})")
                return cached
        
        # Then check guild cache
        channels = list(self.guild.channels)
        logger.debug(f"_find_channel_by_name: guild has {len(channels)} channels: {[c.name for c in channels]}")
        for channel in channels:
            if channel.name.lower() == name_lower:
                if channel_type is None or isinstance(channel, channel_type):
                    logger.debug(f"_find_channel_by_name: found '{channel.name}' (ID: {channel.id}, type={type(channel).__name__})")
                    return channel
                else:
                    logger.debug(f"_find_channel_by_name: name matches '{channel.name}' but type {type(channel).__name__} != {channel_type}")
        logger.debug(f"_find_channel_by_name: no match found for '{name}'")
        return None

    def _find_role_by_name(self, name: str) -> Optional[Role]:
        """Find a role by name (case-insensitive)."""
        name_lower = name.lower()
        logger.debug(f"_find_role_by_name: searching for '{name}'")
        
        # First check session cache
        if name_lower in self._created_roles:
            cached = self._created_roles[name_lower]
            logger.debug(f"_find_role_by_name: found in session cache '{cached.name}' (ID: {cached.id})")
            return cached
        
        # Then check guild cache
        for role in self.guild.roles:
            if role.name.lower() == name_lower:
                logger.debug(f"_find_role_by_name: found '{role.name}' (ID: {role.id})")
                return role
        logger.debug(f"_find_role_by_name: no match found for '{name}'")
        return None

    # ========================================================================
    # Tool Methods
    # ========================================================================

    async def create_channel(self, params: CreateChannelParams) -> ToolResult:
        """
        Create a new channel in the guild.

        Args:
            params: Channel creation parameters.

        Returns:
            ToolResult with success status and channel info.
        """
        channel_type = params.channel_type.lower()
        type_class = TextChannel if channel_type == "text" else VoiceChannel if channel_type == "voice" else CategoryChannel
        existing = self._find_channel_by_name(params.name, type_class)
        if existing:
            if params.category_name:
                if hasattr(existing, 'category') and existing.category:
                    if existing.category.name.lower() == params.category_name.lower():
                        msg = f"Channel '{params.name}' already exists in '{params.category_name}' (ID: {existing.id})"
                        self._log_action(f"Creating {params.channel_type} channel: {params.name}", True)
                        return ToolResult(True, msg, {"channel_id": existing.id, "already_existed": True})
            else:
                msg = f"Channel '{params.name}' already exists (ID: {existing.id})"
                self._log_action(f"Creating {params.channel_type} channel: {params.name}", True)
                return ToolResult(True, msg, {"channel_id": existing.id, "already_existed": True})

        has_perms, error = self._check_permissions("manage_channels")
        if not has_perms:
            self._log_action(f"Creating {params.channel_type} channel: {params.name}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            category = None
            if params.category_name:
                # Try to find the category, with a retry in case it was just created
                category = self._find_channel_by_name(
                    params.category_name, CategoryChannel
                )
                if not category:
                    # Wait a moment and retry - category might have just been created
                    await asyncio.sleep(1.0)
                    category = self._find_channel_by_name(
                        params.category_name, CategoryChannel
                    )
                if not category:
                    return ToolResult(
                        False,
                        f"Category '{params.category_name}' not found. Create the category first using create_category."
                    )

            channel_type = params.channel_type.lower()

            # Build permission overwrites if private or role-specific access
            overwrites = {}
            if params.private or params.allowed_roles or params.denied_roles:
                # Deny @everyone by default if private
                if params.private:
                    overwrites[self.guild.default_role] = PermissionOverwrite(
                        view_channel=False,
                        send_messages=False,
                        connect=False,
                    )

                # Allow specific roles
                if params.allowed_roles:
                    for role_name in params.allowed_roles:
                        role = self._find_role_by_name(role_name)
                        if role:
                            overwrites[role] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                                connect=True,
                                speak=True,
                            )
                        else:
                            logger.warning(f"Role not found: {role_name}")

                # Deny specific roles
                if params.denied_roles:
                    for role_name in params.denied_roles:
                        role = self._find_role_by_name(role_name)
                        if role:
                            overwrites[role] = PermissionOverwrite(
                                view_channel=False,
                                send_messages=False,
                                connect=False,
                            )
                        else:
                            logger.warning(f"Role not found: {role_name}")

                # Always allow the bot
                if self.bot_member:
                    overwrites[self.bot_member] = PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_channels=True,
                        manage_permissions=True,
                    )

            # Build optional kwargs - only include overwrites if we have any
            overwrite_kwargs = {"overwrites": overwrites} if overwrites else {}

            if channel_type == "text":
                channel = await self.guild.create_text_channel(
                    name=params.name,
                    category=category,
                    topic=params.topic,
                    slowmode_delay=params.slowmode_delay or 0,
                    nsfw=params.nsfw,
                    position=params.position,
                    **overwrite_kwargs,
                )
                # Sync permissions with category if requested and no custom overwrites
                if category and params.sync_permissions and not overwrites:
                    await channel.edit(sync_permissions=True)
            elif channel_type == "voice":
                channel = await self.guild.create_voice_channel(
                    name=params.name,
                    category=category,
                    position=params.position,
                    **overwrite_kwargs,
                )
                if category and params.sync_permissions and not overwrites:
                    await channel.edit(sync_permissions=True)
            elif channel_type == "category":
                channel = await self.guild.create_category(
                    name=params.name,
                    position=params.position,
                    **overwrite_kwargs,
                )
            else:
                return ToolResult(
                    False,
                    f"Invalid channel type: {params.channel_type}"
                )

            # Add to session cache so subsequent lookups find it
            self._created_channels[channel.name.lower()] = channel
            logger.debug(f"Added channel '{channel.name}' to session cache")

            access_info = ""
            if params.private:
                access_info = " (private)"
            if params.allowed_roles:
                access_info += f" [allowed: {', '.join(params.allowed_roles)}]"

            msg = f"Created {channel_type} channel '{channel.name}'{access_info}"
            self._log_action(msg, True)
            return ToolResult(True, msg, {"channel_id": channel.id, "channel_name": channel.name})

        except Forbidden:
            msg = "Bot lacks permission to create channels"
            self._log_action(f"Creating {params.channel_type} channel: {params.name}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Creating {params.channel_type} channel: {params.name}", False)
            return ToolResult(False, msg)

    async def create_role(self, params: CreateRoleParams) -> ToolResult:
        """
        Create a new role in the guild.

        Args:
            params: Role creation parameters.

        Returns:
            ToolResult with success status and role info.
        """
        # Check if role already exists
        existing = self._find_role_by_name(params.name)
        if existing:
            msg = f"Role '{params.name}' already exists (ID: {existing.id})"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {"role_id": existing.id, "already_existed": True}
            )

        # Check permissions
        has_perms, error = self._check_permissions("manage_roles")
        if not has_perms:
            self._log_action(f"Creating role '{params.name}': {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            # Parse color
            color = self._parse_color(params.color) or discord.Color.default()

            # Build permissions
            perms = discord.Permissions.none()
            if params.permissions:
                for perm_name in params.permissions:
                    perm_name_lower = perm_name.lower()
                    if perm_name_lower in self.VALID_PERMISSIONS:
                        setattr(perms, perm_name_lower, True)
                    else:
                        logger.warning(f"Unknown permission: {perm_name}")

            role = await self.guild.create_role(
                name=params.name,
                color=color,
                hoist=params.hoist,
                mentionable=params.mentionable,
                permissions=perms,
            )
            
            # Add to session cache so subsequent lookups find it
            self._created_roles[role.name.lower()] = role
            logger.debug(f"Added role '{role.name}' to session cache")

            msg = f"Created role '{role.name}'"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {"role_id": role.id, "role_name": role.name},
            )

        except Forbidden:
            msg = "Bot lacks permission to create roles"
            self._log_action(f"Creating role '{params.name}': {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Creating role '{params.name}': {msg}", False)
            return ToolResult(False, msg)

    async def set_permissions(self, params: SetPermissionsParams) -> ToolResult:
        """
        Set channel-specific permissions for a role or member.

        Args:
            params: Permission setting parameters.

        Returns:
            ToolResult with success status.
        """
        # Check permissions
        has_perms, error = self._check_permissions("manage_channels", "manage_roles")
        if not has_perms:
            self._log_action(f"Setting permissions on '{params.channel_name}' for '{params.target_name}': {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            # Find channel
            channel = self._find_channel_by_name(params.channel_name)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Setting permissions: {msg}", False)
                return ToolResult(False, msg)

            # Find target
            if params.target_type.lower() == "role":
                target = self._find_role_by_name(params.target_name)
                if not target:
                    msg = f"Role '{params.target_name}' not found"
                    self._log_action(f"Setting permissions: {msg}", False)
                    return ToolResult(False, msg)
            else:
                # Find member by name or display name
                target = discord.utils.find(
                    lambda m: m.name.lower() == params.target_name.lower()
                    or m.display_name.lower() == params.target_name.lower(),
                    self.guild.members,
                )
                if not target:
                    msg = f"Member '{params.target_name}' not found"
                    self._log_action(f"Setting permissions: {msg}", False)
                    return ToolResult(False, msg)

            # Build overwrite
            overwrite = PermissionOverwrite()
            for perm_name, value in params.permissions.items():
                perm_name_lower = perm_name.lower()
                if perm_name_lower not in self.VALID_PERMISSIONS:
                    logger.warning(f"Unknown permission: {perm_name}")
                    continue

                if value.lower() == "allow":
                    setattr(overwrite, perm_name_lower, True)
                elif value.lower() == "deny":
                    setattr(overwrite, perm_name_lower, False)
                # 'neutral' leaves it as None (inherit)

            await channel.set_permissions(target, overwrite=overwrite)

            msg = f"Set permissions on '{channel.name}' for '{params.target_name}'"
            self._log_action(msg, True)
            return ToolResult(True, msg)

        except Forbidden:
            msg = "Bot lacks permission to modify permissions"
            self._log_action(f"Setting permissions on '{params.channel_name}': {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Setting permissions on '{params.channel_name}': {msg}", False)
            return ToolResult(False, msg)

    async def create_category(self, params: CreateCategoryParams) -> ToolResult:
        """
        Create a category, optionally with channels inside it.

        Args:
            params: Category creation parameters.

        Returns:
            ToolResult with success status and created items.
        """
        logger.debug(f"create_category called with params: name='{params.name}', private={params.private}, allowed_roles={params.allowed_roles}, denied_roles={params.denied_roles}, channels={params.channels}")

        # Check if category already exists
        logger.debug(f"Checking if category '{params.name}' already exists...")
        existing = self._find_channel_by_name(params.name, CategoryChannel)
        if existing:
            logger.debug(f"Category '{params.name}' already exists with ID {existing.id}")
            msg = f"Category '{params.name}' already exists (ID: {existing.id})"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {"category_id": existing.id, "already_existed": True}
            )

        # Check permissions
        logger.debug("Checking bot permissions for manage_channels...")
        has_perms, error = self._check_permissions("manage_channels")
        if not has_perms:
            logger.error(f"Permission check failed: {error}")
            self._log_action(f"Creating category '{params.name}': {error}", False)
            return ToolResult(False, error)
        logger.debug("Permission check passed")

        logger.debug("Acquiring rate limiter...")
        await self.rate_limiter.acquire()
        logger.debug("Rate limiter acquired")

        try:
            # Build permission overwrites for the category
            overwrites = {}
            logger.debug(f"Building overwrites: private={params.private}, allowed_roles={params.allowed_roles}, denied_roles={params.denied_roles}")
            
            if params.private or params.allowed_roles or params.denied_roles:
                # Deny @everyone by default if private
                if params.private:
                    logger.debug("Setting private: denying @everyone")
                    overwrites[self.guild.default_role] = PermissionOverwrite(
                        view_channel=False,
                        send_messages=False,
                        connect=False,
                    )

                # Allow specific roles
                if params.allowed_roles:
                    for role_name in params.allowed_roles:
                        role = self._find_role_by_name(role_name)
                        if role:
                            logger.debug(f"Adding allow overwrite for role '{role_name}' (ID: {role.id})")
                            overwrites[role] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                                connect=True,
                                speak=True,
                            )
                        else:
                            logger.warning(f"Role not found: {role_name}")

                # Deny specific roles
                if params.denied_roles:
                    for role_name in params.denied_roles:
                        role = self._find_role_by_name(role_name)
                        if role:
                            logger.debug(f"Adding deny overwrite for role '{role_name}' (ID: {role.id})")
                            overwrites[role] = PermissionOverwrite(
                                view_channel=False,
                                send_messages=False,
                                connect=False,
                            )
                        else:
                            logger.warning(f"Role not found: {role_name}")

                # Always allow the bot
                if self.bot_member:
                    logger.debug(f"Adding bot overwrite for {self.bot_member}")
                    overwrites[self.bot_member] = PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_channels=True,
                        manage_permissions=True,
                    )

            logger.debug(f"Final overwrites: {len(overwrites)} entries")
            logger.debug(f"Calling guild.create_category(name='{params.name}', position={params.position}, overwrites={len(overwrites)} entries)")

            # Create the category with permissions
            # Only pass overwrites if we have any - discord.py doesn't accept None
            if overwrites:
                category = await self.guild.create_category(
                    name=params.name,
                    position=params.position,
                    overwrites=overwrites,
                )
            else:
                category = await self.guild.create_category(
                    name=params.name,
                    position=params.position,
                )
            
            logger.info(f"Successfully created category '{category.name}' (ID: {category.id})")
            
            # Add to session cache so subsequent lookups find it
            self._created_channels[category.name.lower()] = category

            # Small delay to ensure Discord propagates the category creation
            await asyncio.sleep(0.5)

            created_channels = []
            failed_channels = []

            # Create child channels if specified (they inherit category permissions)
            if params.channels:
                for ch_config in params.channels:
                    await self.rate_limiter.batch_delay()

                    ch_name = ch_config.get("name", "unnamed")
                    ch_type = ch_config.get("type", "text").lower()
                    ch_topic = ch_config.get("topic", None)

                    try:
                        if ch_type == "text":
                            ch = await self.guild.create_text_channel(
                                name=ch_name,
                                category=category,
                                topic=ch_topic,
                            )
                            # Sync permissions with category
                            await ch.edit(sync_permissions=True)
                        elif ch_type == "voice":
                            ch = await self.guild.create_voice_channel(
                                name=ch_name,
                                category=category,
                            )
                            await ch.edit(sync_permissions=True)
                        else:
                            continue

                        # Add child channel to session cache
                        self._created_channels[ch.name.lower()] = ch
                        logger.debug(f"Added child channel '{ch.name}' to session cache")
                        
                        created_channels.append({
                            "name": ch.name,
                            "id": ch.id,
                            "type": ch_type,
                        })
                    except HTTPException as e:
                        logger.warning(f"Failed to create channel '{ch_name}': {e}")
                        failed_channels.append(ch_name)

            access_info = ""
            if params.private:
                access_info = " (private)"
            if params.allowed_roles:
                access_info += f" [allowed: {', '.join(params.allowed_roles)}]"

            # Build result message
            msg = f"Created category '{category.name}'{access_info} with {len(created_channels)} channels"
            if failed_channels:
                msg += f" ({len(failed_channels)} failed: {', '.join(failed_channels)})"

            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {
                    "category_id": category.id,
                    "category_name": category.name,
                    "channels": created_channels,
                    "failed_channels": failed_channels,
                },
            )

        except Forbidden as e:
            logger.error(f"Forbidden error creating category '{params.name}': {e}")
            msg = f"Bot lacks permission to create channels: {e}"
            self._log_action(f"Creating category '{params.name}': {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            logger.error(f"HTTPException creating category '{params.name}': status={e.status}, code={e.code}, text={e.text}")
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Creating category '{params.name}': {msg}", False)
            return ToolResult(False, msg)
        except Exception as e:
            logger.exception(f"Unexpected error creating category '{params.name}': {e}")
            msg = f"Unexpected error: {str(e)}"
            self._log_action(f"Creating category '{params.name}': {msg}", False)
            return ToolResult(False, msg)

    async def modify_server_settings(
        self,
        params: ModifyServerSettingsParams,
    ) -> ToolResult:
        """
        Modify guild-level settings.

        Args:
            params: Server modification parameters.

        Returns:
            ToolResult with success status.
        """
        # Check permissions
        has_perms, error = self._check_permissions("manage_guild")
        if not has_perms:
            self._log_action(f"Modifying server settings: {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            import aiohttp
            
            kwargs: dict[str, Any] = {}

            if params.name:
                kwargs["name"] = params.name
            
            # Handle icon URL
            if params.icon_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(params.icon_url) as resp:
                            if resp.status == 200:
                                icon_bytes = await resp.read()
                                kwargs["icon"] = icon_bytes
                                logger.info(f"Downloaded server icon from {params.icon_url} ({len(icon_bytes)} bytes)")
                            else:
                                logger.warning(f"Failed to download icon from {params.icon_url}: HTTP {resp.status}")
                                return ToolResult(False, f"Failed to download icon: HTTP {resp.status}")
                except Exception as e:
                    logger.error(f"Error downloading icon from {params.icon_url}: {e}")
                    return ToolResult(False, f"Error downloading icon: {str(e)}")
            
            # Handle banner URL
            if params.banner_url:
                # Check if server has required boost level for banner
                if self.guild.premium_tier < 2:
                    msg = f"Server banner requires boost level 2 or higher (current: {self.guild.premium_tier})"
                    logger.warning(msg)
                    return ToolResult(False, msg)
                
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(params.banner_url) as resp:
                            if resp.status == 200:
                                banner_bytes = await resp.read()
                                kwargs["banner"] = banner_bytes
                                logger.info(f"Downloaded server banner from {params.banner_url} ({len(banner_bytes)} bytes)")
                            else:
                                logger.warning(f"Failed to download banner from {params.banner_url}: HTTP {resp.status}")
                                return ToolResult(False, f"Failed to download banner: HTTP {resp.status}")
                except Exception as e:
                    logger.error(f"Error downloading banner from {params.banner_url}: {e}")
                    return ToolResult(False, f"Error downloading banner: {str(e)}")

            if params.verification_level:
                level_map = {
                    "none": discord.VerificationLevel.none,
                    "low": discord.VerificationLevel.low,
                    "medium": discord.VerificationLevel.medium,
                    "high": discord.VerificationLevel.high,
                    "highest": discord.VerificationLevel.highest,
                }
                level = level_map.get(params.verification_level.lower())
                if level:
                    kwargs["verification_level"] = level

            if params.default_notifications:
                notif_map = {
                    "all_messages": discord.NotificationLevel.all_messages,
                    "only_mentions": discord.NotificationLevel.only_mentions,
                }
                notif = notif_map.get(params.default_notifications.lower())
                if notif:
                    kwargs["default_notifications"] = notif

            if params.afk_channel:
                afk_ch = self._find_channel_by_name(
                    params.afk_channel, VoiceChannel
                )
                if afk_ch:
                    kwargs["afk_channel"] = afk_ch

            if params.afk_timeout:
                valid_timeouts = [60, 300, 900, 1800, 3600]
                if params.afk_timeout in valid_timeouts:
                    kwargs["afk_timeout"] = params.afk_timeout

            if params.system_channel:
                sys_ch = self._find_channel_by_name(
                    params.system_channel, TextChannel
                )
                if sys_ch:
                    kwargs["system_channel"] = sys_ch

            if not kwargs:
                msg = "No valid settings to modify"
                self._log_action(f"Modifying server settings: {msg}", False)
                return ToolResult(False, msg)

            await self.guild.edit(**kwargs)

            msg = f"Modified server settings: {', '.join(kwargs.keys())}"
            self._log_action(msg, True)
            return ToolResult(True, msg)

        except Forbidden:
            msg = "Bot lacks permission to modify server settings"
            self._log_action(f"Modifying server settings: {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Modifying server settings: {msg}", False)
            return ToolResult(False, msg)

    async def delete_channel(self, params: DeleteChannelParams) -> ToolResult:
        """
        Delete a channel from the guild.

        Args:
            params: Channel deletion parameters.

        Returns:
            ToolResult with success status.
        """
        # Protect the envoy-summary channel from deletion
        if params.name.lower() == "envoy-summary":
            msg = "Cannot delete 'envoy-summary' channel - it's required for bot operation"
            self._log_action(f"Deleting channel '{params.name}': {msg}", False)
            return ToolResult(False, msg)

        # Check permissions
        has_perms, error = self._check_permissions("manage_channels")
        if not has_perms:
            self._log_action(f"Deleting channel '{params.name}': {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.name)
            if not channel:
                msg = f"Channel '{params.name}' not found"
                self._log_action(f"Deleting channel: {msg}", False)
                return ToolResult(False, msg)

            channel_name = channel.name
            await channel.delete(reason=params.reason)

            msg = f"Deleted channel '{channel_name}'"
            self._log_action(msg, True)
            return ToolResult(True, msg)

        except Forbidden:
            msg = "Bot lacks permission to delete channels"
            self._log_action(f"Deleting channel '{params.name}': {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Deleting channel '{params.name}': {msg}", False)
            return ToolResult(False, msg)

    async def delete_role(self, params: DeleteRoleParams) -> ToolResult:
        """
        Delete a role from the guild.

        Args:
            params: Role deletion parameters.

        Returns:
            ToolResult with success status.
        """
        # Check permissions
        has_perms, error = self._check_permissions("manage_roles")
        if not has_perms:
            self._log_action(f"Deleting role '{params.name}': {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            role = self._find_role_by_name(params.name)
            if not role:
                msg = f"Role '{params.name}' not found"
                self._log_action(f"Deleting role: {msg}", False)
                return ToolResult(False, msg)

            # Check if we can manage this role
            if not self._can_manage_role(role):
                msg = f"Cannot delete role '{params.name}' - it's higher than bot's role"
                self._log_action(f"Deleting role: {msg}", False)
                return ToolResult(False, msg)

            role_name = role.name
            await role.delete(reason=params.reason)

            msg = f"Deleted role '{role_name}'"
            self._log_action(msg, True)
            return ToolResult(True, msg)

        except Forbidden:
            msg = "Bot lacks permission to delete roles"
            self._log_action(f"Deleting role '{params.name}': {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Deleting role '{params.name}': {msg}", False)
            return ToolResult(False, msg)

    async def delete_category(self, params: DeleteCategoryParams) -> ToolResult:
        """
        Delete a category from the guild, optionally deleting all channels inside.

        Args:
            params: Category deletion parameters.

        Returns:
            ToolResult with success status.
        """
        # Check permissions
        has_perms, error = self._check_permissions("manage_channels")
        if not has_perms:
            self._log_action(f"Deleting category '{params.name}': {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            category = self._find_channel_by_name(params.name, CategoryChannel)
            if not category:
                msg = f"Category '{params.name}' not found"
                self._log_action(f"Deleting category: {msg}", False)
                return ToolResult(False, msg)

            category_name = category.name
            deleted_channels = []

            # Delete channels inside the category first if requested
            if params.delete_channels:
                for channel in category.channels:
                    # Don't delete envoy-summary
                    if channel.name.lower() == "envoy-summary":
                        continue
                    await self.rate_limiter.acquire()
                    await channel.delete(reason=params.reason)
                    deleted_channels.append(channel.name)

            # Delete the category itself
            await category.delete(reason=params.reason)

            if deleted_channels:
                msg = f"Deleted category '{category_name}' and {len(deleted_channels)} channels inside it"
            else:
                msg = f"Deleted category '{category_name}'"
            
            self._log_action(msg, True)
            return ToolResult(True, msg)

        except Forbidden:
            msg = "Bot lacks permission to delete categories"
            self._log_action(f"Deleting category '{params.name}': {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Deleting category '{params.name}': {msg}", False)
            return ToolResult(False, msg)

    async def edit_category(self, params: EditCategoryParams) -> ToolResult:
        """
        Edit an existing category's properties.

        Args:
            params: Category edit parameters.

        Returns:
            ToolResult with success status.
        """
        has_perms, error = self._check_permissions("manage_channels")
        if not has_perms:
            self._log_action(f"Editing category '{params.name}': {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            category = self._find_channel_by_name(params.name, CategoryChannel)
            if not category:
                msg = f"Category '{params.name}' not found"
                self._log_action(f"Editing category: {msg}", False)
                return ToolResult(False, msg)

            kwargs: dict[str, Any] = {}

            if params.new_name:
                kwargs["name"] = params.new_name

            if params.position is not None:
                kwargs["position"] = params.position

            if not kwargs:
                msg = "No changes specified"
                self._log_action(f"Editing category '{params.name}': {msg}", False)
                return ToolResult(False, msg)

            await category.edit(**kwargs)

            changes = ", ".join(kwargs.keys())
            msg = f"Edited category '{params.name}': updated {changes}"
            self._log_action(msg, True)
            return ToolResult(True, msg)

        except Forbidden:
            msg = "Bot lacks permission to edit categories"
            self._log_action(f"Editing category '{params.name}': {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Editing category '{params.name}': {msg}", False)
            return ToolResult(False, msg)

    async def get_server_info(self) -> ToolResult:
        """
        Get current server information including channels, roles, and settings.

        Returns:
            ToolResult with server information.
        """
        try:
            categories = []
            text_channels = []
            voice_channels = []

            for channel in self.guild.channels:
                info = {"name": channel.name, "id": channel.id}
                if isinstance(channel, CategoryChannel):
                    info["children"] = [c.name for c in channel.channels]
                    categories.append(info)
                elif isinstance(channel, TextChannel):
                    info["category"] = channel.category.name if channel.category else None
                    text_channels.append(info)
                elif isinstance(channel, VoiceChannel):
                    info["category"] = channel.category.name if channel.category else None
                    voice_channels.append(info)

            roles = [
                {
                    "name": r.name,
                    "id": r.id,
                    "color": str(r.color),
                    "position": r.position,
                    "mentionable": r.mentionable,
                    "hoist": r.hoist,
                }
                for r in self.guild.roles
                if r.name != "@everyone"
            ]

            # Get additional server metadata
            features = list(self.guild.features) if self.guild.features else []
            description = self.guild.description or ""
            preferred_locale = str(self.guild.preferred_locale) if self.guild.preferred_locale else "en-US"
            
            # Determine server type/purpose from features and other metadata
            server_type_hints = []
            if "COMMUNITY" in features:
                server_type_hints.append("Community Server")
            if "PARTNERED" in features:
                server_type_hints.append("Partnered")
            if "VERIFIED" in features:
                server_type_hints.append("Verified")
            if "DISCOVERABLE" in features:
                server_type_hints.append("Discoverable")
            if "WELCOME_SCREEN_ENABLED" in features:
                server_type_hints.append("Has Welcome Screen")
            if "THREADS_ENABLED" in features:
                server_type_hints.append("Threads Enabled")

            msg = "Fetched server information"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {
                    "name": self.guild.name,
                    "id": self.guild.id,
                    "description": description,
                    "member_count": self.guild.member_count,
                    "preferred_locale": preferred_locale,
                    "features": features,
                    "server_type": ", ".join(server_type_hints) if server_type_hints else "Standard Server",
                    "categories": categories,
                    "text_channels": text_channels,
                    "voice_channels": voice_channels,
                    "roles": roles,
                    "verification_level": str(self.guild.verification_level),
                    "boost_level": self.guild.premium_tier,
                    "boost_count": self.guild.premium_subscription_count or 0,
                    "max_members": self.guild.max_members or "Unknown",
                    "icon_url": str(self.guild.icon.url) if self.guild.icon else None,
                    "banner_url": str(self.guild.banner.url) if self.guild.banner else None,
                },
            )

        except Exception as e:
            msg = f"Error fetching server info: {str(e)}"
            self._log_action(msg, False)
            return ToolResult(False, msg)

    async def export_server(self) -> ToolResult:
        """
        Export the entire server structure to a dictionary.

        Exports: categories, channels, roles, permissions, webhooks, server settings.
        Does NOT export: messages, member data, invites.

        Returns:
            ToolResult with complete server data as a dictionary.
        """
        try:
            export_data = {
                "version": "1.0",
                "exported_at": discord.utils.utcnow().isoformat(),
                "server": {
                    "name": self.guild.name,
                    "id": self.guild.id,
                    "description": self.guild.description,
                    "verification_level": str(self.guild.verification_level),
                    "default_notifications": str(self.guild.default_notifications),
                    "explicit_content_filter": str(self.guild.explicit_content_filter),
                    "afk_timeout": self.guild.afk_timeout,
                    "afk_channel": self.guild.afk_channel.name if self.guild.afk_channel else None,
                    "system_channel": self.guild.system_channel.name if self.guild.system_channel else None,
                    "rules_channel": self.guild.rules_channel.name if self.guild.rules_channel else None,
                    "public_updates_channel": self.guild.public_updates_channel.name if self.guild.public_updates_channel else None,
                },
                "roles": [],
                "categories": [],
                "channels": [],
                "webhooks": [],
            }

            # Export roles (excluding @everyone and bot-managed roles)
            for role in sorted(self.guild.roles, key=lambda r: -r.position):
                if role.name == "@everyone":
                    continue
                if role.managed:  # Skip bot/integration roles
                    continue

                role_data = {
                    "name": role.name,
                    "color": str(role.color),
                    "hoist": role.hoist,
                    "mentionable": role.mentionable,
                    "position": role.position,
                    "permissions": role.permissions.value,
                }
                export_data["roles"].append(role_data)

            # Export categories with their permission overwrites
            for category in self.guild.categories:
                cat_data = {
                    "name": category.name,
                    "position": category.position,
                    "overwrites": [],
                }

                for target, overwrite in category.overwrites.items():
                    ow_data = {
                        "type": "role" if isinstance(target, Role) else "member",
                        "name": target.name if isinstance(target, Role) else str(target.id),
                        "allow": overwrite.pair()[0].value,
                        "deny": overwrite.pair()[1].value,
                    }
                    cat_data["overwrites"].append(ow_data)

                export_data["categories"].append(cat_data)

            # Export channels
            for channel in self.guild.channels:
                if isinstance(channel, CategoryChannel):
                    continue  # Already handled above

                channel_data = {
                    "name": channel.name,
                    "type": "text" if isinstance(channel, TextChannel) else "voice" if isinstance(channel, VoiceChannel) else "other",
                    "category": channel.category.name if channel.category else None,
                    "position": channel.position,
                    "overwrites": [],
                }

                # Channel-specific properties
                if isinstance(channel, TextChannel):
                    channel_data["topic"] = channel.topic
                    channel_data["slowmode_delay"] = channel.slowmode_delay
                    channel_data["nsfw"] = channel.is_nsfw()
                elif isinstance(channel, VoiceChannel):
                    channel_data["bitrate"] = channel.bitrate
                    channel_data["user_limit"] = channel.user_limit

                # Permission overwrites
                for target, overwrite in channel.overwrites.items():
                    ow_data = {
                        "type": "role" if isinstance(target, Role) else "member",
                        "name": target.name if isinstance(target, Role) else str(target.id),
                        "allow": overwrite.pair()[0].value,
                        "deny": overwrite.pair()[1].value,
                    }
                    channel_data["overwrites"].append(ow_data)

                export_data["channels"].append(channel_data)

            # Export webhooks (for channels we can access)
            try:
                webhooks = await self.guild.webhooks()
                for webhook in webhooks:
                    if webhook.channel:
                        webhook_data = {
                            "name": webhook.name,
                            "channel": webhook.channel.name,
                            "avatar_url": str(webhook.avatar.url) if webhook.avatar else None,
                        }
                        export_data["webhooks"].append(webhook_data)
            except (Forbidden, HTTPException):
                logger.warning("Could not export webhooks - missing permissions")

            msg = (
                f"Exported server structure: {len(export_data['roles'])} roles, "
                f"{len(export_data['categories'])} categories, "
                f"{len(export_data['channels'])} channels, "
                f"{len(export_data['webhooks'])} webhooks"
            )
            self._log_action(msg, True)
            return ToolResult(True, msg, export_data)

        except Exception as e:
            logger.exception(f"Error exporting server: {e}")
            msg = f"Error exporting server: {str(e)}"
            self._log_action(msg, False)
            return ToolResult(False, msg)

    async def import_server(self, data: dict, clear_existing: bool = False) -> ToolResult:
        """
        Import a server structure from exported data.

        Args:
            data: The exported server data dictionary.
            clear_existing: If True, delete existing channels/roles before importing.

        Returns:
            ToolResult with import summary.
        """
        try:
            if data.get("version") != "1.0":
                msg = f"Unsupported export version: {data.get('version')}"
                self._log_action(msg, False)
                return ToolResult(False, msg)

            stats = {
                "roles_created": 0,
                "categories_created": 0,
                "channels_created": 0,
                "webhooks_created": 0,
                "errors": [],
            }

            # Optionally clear existing content (except system channels)
            if clear_existing:
                # Delete channels (except system ones)
                for channel in list(self.guild.channels):
                    if channel.name == "envoy-summary":
                        continue
                    if channel == self.guild.system_channel:
                        continue
                    if channel == self.guild.rules_channel:
                        continue
                    try:
                        await self.rate_limiter.acquire()
                        await channel.delete(reason="Envoy import - clearing existing content")
                    except (Forbidden, HTTPException) as e:
                        stats["errors"].append(f"Could not delete channel {channel.name}: {e}")

                # Delete roles (except @everyone and managed roles)
                for role in list(self.guild.roles):
                    if role.name == "@everyone" or role.managed:
                        continue
                    if role >= self.bot_top_role:
                        continue
                    try:
                        await self.rate_limiter.acquire()
                        await role.delete(reason="Envoy import - clearing existing content")
                    except (Forbidden, HTTPException) as e:
                        stats["errors"].append(f"Could not delete role {role.name}: {e}")

            # Create roles (bottom to top for proper positioning)
            role_map: dict[str, Role] = {}  # name -> created role
            roles_to_create = list(reversed(data.get("roles", [])))

            for role_data in roles_to_create:
                try:
                    await self.rate_limiter.acquire() 
                    color = discord.Color.default()
                    if role_data.get("color") and role_data["color"] != "#000000":
                        try:
                            color = discord.Color(int(role_data["color"].lstrip("#"), 16))
                        except ValueError:
                            pass

                    perms = discord.Permissions(role_data.get("permissions", 0))

                    new_role = await self.guild.create_role(
                        name=role_data["name"],
                        color=color,
                        hoist=role_data.get("hoist", False),
                        mentionable=role_data.get("mentionable", False),
                        permissions=perms,
                        reason="Envoy import",
                    )
                    role_map[role_data["name"]] = new_role
                    stats["roles_created"] += 1
                except (Forbidden, HTTPException) as e:
                    stats["errors"].append(f"Could not create role {role_data['name']}: {e}")

            # Create categories
            cat_map: dict[str, CategoryChannel] = {}  # name -> created category

            for cat_data in sorted(data.get("categories", []), key=lambda c: c.get("position", 0)):
                try:
                    await self.rate_limiter.acquire()

                    # Build permission overwrites
                    overwrites = {}
                    for ow in cat_data.get("overwrites", []):
                        if ow["type"] == "role":
                            if ow["name"] == "@everyone":
                                target = self.guild.default_role
                            else:
                                target = role_map.get(ow["name"]) or discord.utils.get(self.guild.roles, name=ow["name"])
                            if target:
                                overwrites[target] = PermissionOverwrite.from_pair(
                                    discord.Permissions(ow["allow"]),
                                    discord.Permissions(ow["deny"]),
                                )

                    new_cat = await self.guild.create_category(
                        name=cat_data["name"],
                        overwrites=overwrites,
                        reason="Envoy import",
                    )
                    cat_map[cat_data["name"]] = new_cat
                    stats["categories_created"] += 1
                except (Forbidden, HTTPException) as e:
                    stats["errors"].append(f"Could not create category {cat_data['name']}: {e}")

            # Create channels
            for ch_data in sorted(data.get("channels", []), key=lambda c: c.get("position", 0)):
                try:
                    await self.rate_limiter.acquire()

                    # Build permission overwrites
                    overwrites = {}
                    for ow in ch_data.get("overwrites", []):
                        if ow["type"] == "role":
                            if ow["name"] == "@everyone":
                                target = self.guild.default_role
                            else:
                                target = role_map.get(ow["name"]) or discord.utils.get(self.guild.roles, name=ow["name"])
                            if target:
                                overwrites[target] = PermissionOverwrite.from_pair(
                                    discord.Permissions(ow["allow"]),
                                    discord.Permissions(ow["deny"]),
                                )

                    category = cat_map.get(ch_data.get("category")) if ch_data.get("category") else None

                    if ch_data["type"] == "text":
                        await self.guild.create_text_channel(
                            name=ch_data["name"],
                            category=category,
                            topic=ch_data.get("topic"),
                            slowmode_delay=ch_data.get("slowmode_delay", 0),
                            nsfw=ch_data.get("nsfw", False),
                            overwrites=overwrites,
                            reason="Envoy import",
                        )
                        stats["channels_created"] += 1
                    elif ch_data["type"] == "voice":
                        await self.guild.create_voice_channel(
                            name=ch_data["name"],
                            category=category,
                            bitrate=ch_data.get("bitrate", 64000),
                            user_limit=ch_data.get("user_limit", 0),
                            overwrites=overwrites,
                            reason="Envoy import",
                        )
                        stats["channels_created"] += 1
                except (Forbidden, HTTPException) as e:
                    stats["errors"].append(f"Could not create channel {ch_data['name']}: {e}")

            # Create webhooks
            for wh_data in data.get("webhooks", []):
                try:
                    await self.rate_limiter.acquire()
                    channel = discord.utils.get(self.guild.text_channels, name=wh_data["channel"])
                    if channel:
                        await channel.create_webhook(
                            name=wh_data["name"],
                            reason="Envoy import",
                        )
                        stats["webhooks_created"] += 1
                except (Forbidden, HTTPException) as e:
                    stats["errors"].append(f"Could not create webhook {wh_data['name']}: {e}")

            # Update server settings if present
            server_settings = data.get("server", {})
            if server_settings.get("name"):
                try:
                    await self.rate_limiter.acquire()
                    await self.guild.edit(
                        name=server_settings["name"],
                        description=server_settings.get("description"),
                        reason="Envoy import - server settings",
                    )
                except (Forbidden, HTTPException) as e:
                    stats["errors"].append(f"Could not update server settings: {e}")

            summary = (
                f"Import complete: {stats['roles_created']} roles, "
                f"{stats['categories_created']} categories, "
                f"{stats['channels_created']} channels, "
                f"{stats['webhooks_created']} webhooks"
            )
            if stats["errors"]:
                summary += f"\n⚠️ {len(stats['errors'])} errors occurred"

            self._log_action(summary, True)
            return ToolResult(True, summary, stats)

        except Exception as e:
            logger.exception(f"Error importing server: {e}")
            msg = f"Error importing server: {str(e)}"
            self._log_action(msg, False)
            return ToolResult(False, msg)

    async def ask_user(self, params: AskUserParams) -> ToolResult:
        """
        Ask the user a question mid-task and wait for their response.

        This method signals to the main bot that a question needs to be asked,
        then waits for the answer to be provided via set_user_answer().

        Args:
            params: Question parameters including the question and optional context/options.

        Returns:
            ToolResult with the user's answer.
        """
        logger.debug(f"ask_user called: question='{params.question}', context='{params.context}', options={params.options}")

        # Store the pending question
        self._pending_question = {
            "question": params.question,
            "context": params.context,
            "options": params.options,
        }

        # Signal that a question is pending
        self._question_event.set()
        self._answer_event.clear()

        logger.debug("Waiting for user answer...")

        # Wait for the answer (with timeout)
        try:
            await asyncio.wait_for(self._answer_event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            self._pending_question = None
            self._question_event.clear()
            msg = "User did not respond within 5 minutes"
            self._log_action(f"Asked user: {params.question} - {msg}", False)
            return ToolResult(False, msg)

        # Get the answer
        answer = self._question_answer
        self._question_answer = None
        self._pending_question = None
        self._question_event.clear()

        logger.info(f"User answered: {answer}")

        msg = f"User answered: {answer}"
        self._log_action(f"Asked user: {params.question} - {msg}", True)
        return ToolResult(
            True,
            msg,
            {"answer": answer},
        )

    def set_user_answer(self, answer: str) -> None:
        """
        Set the user's answer to a pending question.

        Args:
            answer: The user's response.
        """
        logger.debug(f"set_user_answer called with: {answer}")
        self._question_answer = answer
        self._answer_event.set()

    def has_pending_question(self) -> bool:
        """Check if there's a pending question waiting for an answer."""
        return self._question_event.is_set()

    def get_pending_question(self) -> Optional[dict[str, Any]]:
        """Get the current pending question, if any."""
        return self._pending_question

    def clear_question_state(self) -> None:
        """Clear the question state (e.g., on cancellation)."""
        self._pending_question = None
        self._question_answer = None
        self._question_event.clear()
        self._answer_event.clear()

    # ========================================================================
    # Webhook Methods
    # ========================================================================

    async def get_or_create_webhook(
        self,
        channel: TextChannel,
        webhook_name: str = "Envoy",
    ) -> Optional[discord.Webhook]:
        """
        Get an existing webhook or create a new one for a channel.

        Args:
            channel: The text channel.
            webhook_name: Name for the webhook.

        Returns:
            The webhook object, or None if creation failed.
        """
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.name == webhook_name:
                    return wh

            # Create new webhook
            webhook = await channel.create_webhook(
                name=webhook_name,
                reason="Created by Envoy bot for embed posting",
            )
            return webhook
        except Exception as e:
            logger.error(f"Failed to get/create webhook: {e}")
            return None

    async def create_webhook(self, params: CreateWebhookParams) -> ToolResult:
        """
        Create a webhook in a channel.

        Args:
            params: Webhook creation parameters.

        Returns:
            ToolResult with the webhook URL.
        """
        has_perms, error = self._check_permissions("manage_webhooks")
        if not has_perms:
            self._log_action(f"Creating webhook in {params.channel_name} - {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name, TextChannel)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Creating webhook in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            webhook = await self.get_or_create_webhook(channel, params.webhook_name)
            if not webhook:
                msg = "Failed to create webhook"
                self._log_action(f"Creating webhook in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            msg = f"Webhook created in #{params.channel_name}"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {"webhook_url": webhook.url, "webhook_id": webhook.id},
            )

        except Forbidden:
            msg = "Bot lacks permission to manage webhooks"
            self._log_action(f"Creating webhook in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Creating webhook in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)

    async def post_webhook_embed(self, params: PostWebhookEmbedParams) -> ToolResult:
        """
        Post an embed message via webhook (allows user to edit later).

        Args:
            params: Embed posting parameters.

        Returns:
            ToolResult with success status.
        """
        has_perms, error = self._check_permissions("manage_webhooks")
        if not has_perms:
            self._log_action(f"Posting embed to {params.channel_name} - {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name, TextChannel)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Posting embed to {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            webhook = await self.get_or_create_webhook(
                channel,
                params.webhook_name or "Envoy",
            )
            if not webhook:
                msg = "Failed to get/create webhook"
                self._log_action(f"Posting embed to {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            # Parse color
            color = discord.Color.blue()
            if params.color:
                try:
                    color_hex = params.color.lstrip("#")
                    color = discord.Color(int(color_hex, 16))
                except ValueError:
                    pass

            # Build embed
            embed = discord.Embed(
                title=params.title,
                description=params.description,
                color=color,
            )

            if params.fields:
                for field in params.fields:
                    embed.add_field(
                        name=field.get("name", "Field"),
                        value=field.get("value", ""),
                        inline=field.get("inline", False),
                    )

            if params.footer:
                embed.set_footer(text=params.footer)

            if params.image_url:
                embed.set_image(url=params.image_url)

            if params.thumbnail_url:
                embed.set_thumbnail(url=params.thumbnail_url)

            # Send via webhook and get message back
            message = await webhook.send(
                embed=embed,
                username=params.webhook_name or "Envoy",
                avatar_url=params.webhook_avatar,
                wait=True,  # Returns the message so we can get its ID
            )

            msg = f"Posted embed '{params.title}' to #{params.channel_name} | Message ID: {message.id} (save this to edit/delete later)"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {"webhook_url": webhook.url, "message_id": message.id, "channel_id": channel.id},
            )

        except Forbidden:
            msg = "Bot lacks permission to use webhooks"
            self._log_action(f"Posting embed to {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Posting embed to {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)

    async def get_channel_webhook(self, params: GetWebhookParams) -> ToolResult:
        """
        Get or create a webhook for a channel and return its URL.

        Args:
            params: Channel parameters.

        Returns:
            ToolResult with the webhook URL.
        """
        has_perms, error = self._check_permissions("manage_webhooks")
        if not has_perms:
            self._log_action(f"Getting webhook for {params.channel_name} - {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name, TextChannel)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Getting webhook for {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            webhook = await self.get_or_create_webhook(channel, "Envoy")
            if not webhook:
                msg = "Failed to get/create webhook"
                self._log_action(f"Getting webhook for {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            msg = f"Webhook URL for #{params.channel_name}: {webhook.url}"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {"webhook_url": webhook.url, "channel_name": params.channel_name},
            )

        except Forbidden:
            msg = "Bot lacks permission to manage webhooks"
            self._log_action(f"Getting webhook for {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Getting webhook for {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)

    async def edit_webhook_message(self, params: EditWebhookMessageParams) -> ToolResult:
        """
        Edit an existing webhook message.

        Args:
            params: Edit parameters including message_id and new content.

        Returns:
            ToolResult with success status.
        """
        has_perms, error = self._check_permissions("manage_webhooks")
        if not has_perms:
            self._log_action(f"Editing webhook message {params.message_id} in {params.channel_name} - {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name, TextChannel)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Editing webhook message {params.message_id} in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            webhook = await self.get_or_create_webhook(channel, "Envoy")
            if not webhook:
                msg = "Failed to get webhook"
                self._log_action(f"Editing webhook message {params.message_id} in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            # Fetch the existing message to get current embed
            try:
                message = await webhook.fetch_message(params.message_id)
            except discord.NotFound:
                msg = f"Message {params.message_id} not found. Make sure it was posted by the Envoy webhook."
                self._log_action(f"Editing webhook message {params.message_id} in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            # Get existing embed or create new one
            old_embed = message.embeds[0] if message.embeds else discord.Embed()

            # Build new embed, keeping old values for unspecified fields
            embed = discord.Embed(
                title=params.title if params.title is not None else old_embed.title,
                description=params.description if params.description is not None else old_embed.description,
                color=old_embed.color,
            )

            # Update color if specified
            if params.color:
                try:
                    color_hex = params.color.lstrip("#")
                    embed.color = discord.Color(int(color_hex, 16))
                except ValueError:
                    pass

            # Handle fields - if new fields provided, replace all; otherwise keep old
            if params.fields is not None:
                for field in params.fields:
                    embed.add_field(
                        name=field.get("name", "Field"),
                        value=field.get("value", ""),
                        inline=field.get("inline", False),
                    )
            else:
                for field in old_embed.fields:
                    embed.add_field(name=field.name, value=field.value, inline=field.inline)

            # Footer
            if params.footer is not None:
                embed.set_footer(text=params.footer)
            elif old_embed.footer:
                embed.set_footer(text=old_embed.footer.text)

            # Images
            if params.image_url is not None:
                embed.set_image(url=params.image_url)
            elif old_embed.image:
                embed.set_image(url=old_embed.image.url)

            if params.thumbnail_url is not None:
                embed.set_thumbnail(url=params.thumbnail_url)
            elif old_embed.thumbnail:
                embed.set_thumbnail(url=old_embed.thumbnail.url)

            # Edit the message
            await webhook.edit_message(params.message_id, embed=embed)

            msg = f"Updated embed in #{params.channel_name} (message ID: {params.message_id})"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
                {"message_id": params.message_id},
            )

        except Forbidden:
            msg = "Bot lacks permission to edit webhook messages"
            self._log_action(f"Editing webhook message {params.message_id} in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Editing webhook message {params.message_id} in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)

    async def delete_webhook_message(self, params: DeleteWebhookMessageParams) -> ToolResult:
        """
        Delete a webhook message.

        Args:
            params: Delete parameters including message_id.

        Returns:
            ToolResult with success status.
        """
        has_perms, error = self._check_permissions("manage_webhooks")
        if not has_perms:
            self._log_action(f"Deleting webhook message {params.message_id} in {params.channel_name} - {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name, TextChannel)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Deleting webhook message {params.message_id} in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            webhook = await self.get_or_create_webhook(channel, "Envoy")
            if not webhook:
                msg = "Failed to get webhook"
                self._log_action(f"Deleting webhook message {params.message_id} in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            try:
                await webhook.delete_message(params.message_id)
            except discord.NotFound:
                msg = f"Message {params.message_id} not found or already deleted"
                self._log_action(f"Deleting webhook message {params.message_id} in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            msg = f"Deleted message {params.message_id} from #{params.channel_name}"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
            )

        except Forbidden:
            msg = "Bot lacks permission to delete webhook messages"
            self._log_action(f"Deleting webhook message {params.message_id} in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Deleting webhook message {params.message_id} in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)

    async def list_webhook_messages(self, params: ListWebhookMessagesParams) -> ToolResult:
        """
        List recent messages from the Envoy webhook in a channel.

        Args:
            params: Channel and limit parameters.

        Returns:
            ToolResult with list of message IDs and previews.
        """
        has_perms, error = self._check_permissions("read_message_history")
        if not has_perms:
            self._log_action(f"Listing webhook messages in {params.channel_name} - {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name, TextChannel)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Listing webhook messages in {params.channel_name} - {msg}", False)
                return ToolResult(False, msg)

            # Get webhooks to find Envoy webhook ID
            webhooks = await channel.webhooks()
            envoy_webhook_ids = [wh.id for wh in webhooks if wh.name == "Envoy"]

            if not envoy_webhook_ids:
                msg = f"No Envoy webhook found in #{params.channel_name}"
                self._log_action(msg, True)
                return ToolResult(
                    True,
                    msg,
                    {"messages": []},
                )

            # Find messages from Envoy webhook
            limit = min(max(params.limit, 1), 50)
            found_messages = []

            async for message in channel.history(limit=100):  # Search through more to find webhook msgs
                if message.webhook_id and message.webhook_id in envoy_webhook_ids:
                    embed_title = message.embeds[0].title if message.embeds else "(no embed)"
                    found_messages.append({
                        "id": message.id,
                        "title": embed_title,
                        "created_at": message.created_at.isoformat(),
                    })
                    if len(found_messages) >= limit:
                        break

            if not found_messages:
                msg = f"No Envoy webhook messages found in #{params.channel_name}"
                self._log_action(msg, True)
                return ToolResult(
                    True,
                    msg,
                    {"messages": []},
                )

            # Format response
            lines = [f"Found {len(found_messages)} Envoy webhook message(s) in #{params.channel_name}:"]
            for msg in found_messages:
                lines.append(f"  • ID: {msg['id']} | Title: {msg['title']}")

            msg = "\n".join(lines)
            self._log_action(f"Listed {len(found_messages)} webhook messages in {params.channel_name}", True)
            return ToolResult(
                True,
                msg,
                {"messages": found_messages},
            )

        except Forbidden:
            msg = "Bot lacks permission to read message history"
            self._log_action(f"Listing webhook messages in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Listing webhook messages in {params.channel_name} - {msg}", False)
            return ToolResult(False, msg)

    # ========================================================================
    # Advanced Permission and Channel Management Methods
    # ========================================================================

    async def set_category_permissions(
        self,
        params: SetCategoryPermissionsParams,
    ) -> ToolResult:
        """
        Set permissions on a category and optionally sync to child channels.

        Args:
            params: Category permission parameters.

        Returns:
            ToolResult with success status.
        """
        self._log_action(
            f"Setting category permissions on '{params.category_name}'"
        )

        has_perms, error = self._check_permissions("manage_channels", "manage_roles")
        if not has_perms:
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            category = self._find_channel_by_name(params.category_name, CategoryChannel)
            if not category:
                return ToolResult(
                    False,
                    f"Category '{params.category_name}' not found"
                )

            roles_updated = []

            for role_name, perms_dict in params.role_permissions.items():
                role = self._find_role_by_name(role_name)
                if not role:
                    logger.warning(f"Role not found: {role_name}")
                    continue

                overwrite = PermissionOverwrite()
                for perm_name, value in perms_dict.items():
                    perm_name_lower = perm_name.lower()
                    if perm_name_lower not in self.VALID_PERMISSIONS:
                        continue

                    if value.lower() == "allow":
                        setattr(overwrite, perm_name_lower, True)
                    elif value.lower() == "deny":
                        setattr(overwrite, perm_name_lower, False)

                await self.rate_limiter.batch_delay()
                await category.set_permissions(role, overwrite=overwrite)
                roles_updated.append(role_name)

            # Sync to child channels if requested
            synced_channels = []
            if params.sync_to_channels:
                for channel in category.channels:
                    await self.rate_limiter.batch_delay()
                    try:
                        await channel.edit(sync_permissions=True)
                        synced_channels.append(channel.name)
                    except Exception as e:
                        logger.warning(f"Failed to sync {channel.name}: {e}")

            msg = f"Updated permissions for roles: {', '.join(roles_updated)}"
            if synced_channels:
                msg += f". Synced {len(synced_channels)} channels."

            return ToolResult(True, msg)

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to modify permissions")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")

    async def make_channel_private(
        self,
        params: MakeChannelPrivateParams,
    ) -> ToolResult:
        """
        Make a channel private, accessible only to specific roles.

        Args:
            params: Channel privacy parameters.

        Returns:
            ToolResult with success status.
        """
        has_perms, error = self._check_permissions("manage_channels", "manage_roles")
        if not has_perms:
            self._log_action(f"Making channel '{params.channel_name}' private - {error}", False)
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name)
            if not channel:
                msg = f"Channel '{params.channel_name}' not found"
                self._log_action(f"Making channel '{params.channel_name}' private - {msg}", False)
                return ToolResult(False, msg)

            # Deny @everyone if requested
            if params.deny_everyone:
                await channel.set_permissions(
                    self.guild.default_role,
                    view_channel=False,
                    send_messages=False,
                    connect=False,
                )

            # Allow specific roles
            allowed = []
            for role_name in params.allowed_roles:
                role = self._find_role_by_name(role_name)
                if role:
                    await self.rate_limiter.batch_delay()
                    await channel.set_permissions(
                        role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        connect=True,
                        speak=True,
                    )
                    allowed.append(role_name)
                else:
                    logger.warning(f"Role not found: {role_name}")

            # Ensure bot can still access
            if self.bot_member:
                await channel.set_permissions(
                    self.bot_member,
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                )

            msg = f"Made '{channel.name}' private. Allowed roles: {', '.join(allowed)}"
            self._log_action(msg, True)
            return ToolResult(
                True,
                msg,
            )

        except Forbidden:
            msg = "Bot lacks permission to modify permissions"
            self._log_action(f"Making channel '{params.channel_name}' private - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Making channel '{params.channel_name}' private - {msg}", False)
            return ToolResult(False, msg)

    async def auto_configure_permissions(
        self,
        params: AutoConfigurePermissionsParams,
    ) -> ToolResult:
        """
        Automatically configure permissions for all categories and channels based on a template.
        
        This acts as a "sub-agent" that handles all permission configuration in one call,
        applying professional permission patterns without requiring multiple tool calls.
        
        **STRATEGY**: Permissions are set at the CATEGORY level (not individual channels).
        Child channels inherit/sync from their category, so setting category permissions
        automatically applies to all channels inside. Only set channel-specific permissions
        for special cases (e.g., read-only announcement channels that need different rules).

        Args:
            params: Permission configuration parameters.

        Returns:
            ToolResult with summary of changes made.
        """
        logger.info(f"auto_configure_permissions: template={params.template}, staff_roles={params.staff_roles}, info_cats={params.info_categories}, staff_cats={params.staff_categories}")

        has_perms, error = self._check_permissions("manage_channels", "manage_roles")
        if not has_perms:
            self._log_action(f"Auto-configuring permissions with '{params.template}' template - {error}", False)
            return ToolResult(False, error)

        try:
            results = {
                "categories_updated": [],
                "channels_updated": [],
                "errors": [],
            }
            
            # Get the default role (@everyone)
            everyone_role = self.guild.default_role
            
            # Find staff roles
            staff_role_objs = []
            for role_name in params.staff_roles:
                role = self._find_role_by_name(role_name)
                if role:
                    staff_role_objs.append(role)
                else:
                    results["errors"].append(f"Staff role '{role_name}' not found")
            
            # Find member role if specified
            member_role_obj = None
            if params.member_role:
                member_role_obj = self._find_role_by_name(params.member_role)
                if not member_role_obj:
                    results["errors"].append(f"Member role '{params.member_role}' not found")
            
            # Normalize category/channel names for matching (lowercase, strip emojis optional)
            def normalize_name(name: str) -> str:
                """Normalize name for matching - lowercase and strip common separators."""
                return name.lower().strip()
            
            def matches_pattern(channel_name: str, patterns: list[str]) -> bool:
                """Check if channel name matches any of the patterns."""
                normalized = normalize_name(channel_name)
                for pattern in patterns:
                    pattern_norm = normalize_name(pattern)
                    if pattern_norm in normalized or normalized in pattern_norm:
                        return True
                return False
            
            # ========== CATEGORY-LEVEL PERMISSIONS (primary approach) ==========
            # Process all categories and sync permissions to child channels
            for category in self.guild.categories:
                await self.rate_limiter.batch_delay()
                
                try:
                    is_info = matches_pattern(category.name, params.info_categories)
                    is_staff = matches_pattern(category.name, params.staff_categories)
                    
                    overwrites = {}
                    
                    if is_staff:
                        # Staff-only category: deny @everyone, allow staff roles
                        overwrites[everyone_role] = PermissionOverwrite(
                            view_channel=False,
                            send_messages=False,
                            connect=False,
                        )
                        for staff_role in staff_role_objs:
                            overwrites[staff_role] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                                connect=True,
                                speak=True,
                                manage_messages=True,
                            )
                        # Ensure bot access
                        if self.bot_member:
                            overwrites[self.bot_member] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                manage_channels=True,
                                manage_messages=True,
                            )
                        results["categories_updated"].append(f"{category.name} (staff-only)")
                        
                    elif is_info:
                        # Info/read-only category: allow view, deny send for @everyone
                        overwrites[everyone_role] = PermissionOverwrite(
                            view_channel=True,
                            send_messages=False,
                            add_reactions=False,
                            create_public_threads=False,
                            create_private_threads=False,
                        )
                        # Staff can still send
                        for staff_role in staff_role_objs:
                            overwrites[staff_role] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                manage_messages=True,
                            )
                        results["categories_updated"].append(f"{category.name} (read-only)")
                        
                    elif params.template == "professional":
                        # Professional template: moderate permissions for general categories
                        # Members can view and chat, but no @everyone mentions by default
                        if member_role_obj:
                            overwrites[everyone_role] = PermissionOverwrite(
                                view_channel=False,
                            )
                            overwrites[member_role_obj] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                                mention_everyone=False,
                            )
                        else:
                            # No member role - use @everyone with restrictions
                            overwrites[everyone_role] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                mention_everyone=False,
                            )
                        # Staff get extra permissions
                        for staff_role in staff_role_objs:
                            overwrites[staff_role] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                manage_messages=True,
                                mention_everyone=True,
                            )
                        results["categories_updated"].append(f"{category.name} (standard)")
                    
                    elif params.template == "private":
                        # Private template: require member role for access
                        overwrites[everyone_role] = PermissionOverwrite(
                            view_channel=False,
                        )
                        if member_role_obj:
                            overwrites[member_role_obj] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                            )
                        for staff_role in staff_role_objs:
                            overwrites[staff_role] = PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                manage_messages=True,
                            )
                        results["categories_updated"].append(f"{category.name} (private)")
                    
                    else:
                        # Community/gaming templates: more open
                        overwrites[everyone_role] = PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            mention_everyone=False,
                        )
                        results["categories_updated"].append(f"{category.name} (open)")
                    
                    # Apply overwrites to category
                    if overwrites:
                        await category.edit(overwrites=overwrites)
                        
                        # Sync permissions to child channels (most efficient approach)
                        for channel in category.channels:
                            await self.rate_limiter.batch_delay()
                            try:
                                await channel.edit(sync_permissions=True)
                            except Exception as e:
                                logger.warning(f"Failed to sync {channel.name}: {e}")
                        
                except Exception as e:
                    results["errors"].append(f"Category {category.name}: {str(e)}")
                    logger.error(f"Error configuring category {category.name}: {e}")
            
            # ========== CHANNEL-LEVEL EXCEPTIONS (only for special cases) ==========
            # Only set individual channel permissions for announcement/special channels
            # that need different permissions than their parent category
            for channel_name in params.announcement_channels:
                channel = self._find_channel_by_name(channel_name)
                if channel and not isinstance(channel, CategoryChannel):
                    try:
                        await self.rate_limiter.batch_delay()
                        # Apply special read-only override if needed
                        await channel.set_permissions(
                            everyone_role,
                            send_messages=False,
                            add_reactions=True,  # Allow reactions for engagement
                        )
                        for staff_role in staff_role_objs:
                            await channel.set_permissions(
                                staff_role,
                                send_messages=True,
                                manage_messages=True,
                            )
                        results["channels_updated"].append(f"{channel.name} (read-only override)")
                    except Exception as e:
                        results["errors"].append(f"Channel {channel_name}: {str(e)}")
            
            # Build result message
            msg_parts = []
            if results["categories_updated"]:
                msg_parts.append(f"Categories: {', '.join(results['categories_updated'])}")
            if results["channels_updated"]:
                msg_parts.append(f"Channels: {', '.join(results['channels_updated'])}")
            if results["errors"]:
                msg_parts.append(f"Errors: {len(results['errors'])}")
            
            success_msg = "Permission configuration complete. " + " | ".join(msg_parts)
            
            self._log_action(f"Auto-configured permissions with '{params.template}' template", True)
            return ToolResult(
                True,
                success_msg,
                results,
            )

        except Forbidden:
            msg = "Bot lacks permission to modify permissions"
            self._log_action(f"Auto-configuring permissions with '{params.template}' template - {msg}", False)
            return ToolResult(False, msg)
        except HTTPException as e:
            msg = f"Discord API error: {e.text}"
            self._log_action(f"Auto-configuring permissions with '{params.template}' template - {msg}", False)
            return ToolResult(False, msg)
        except Exception as e:
            logger.exception(f"Error in auto_configure_permissions: {e}")
            msg = f"Error configuring permissions: {str(e)}"
            self._log_action(f"Auto-configuring permissions with '{params.template}' template - {msg}", False)
            return ToolResult(False, msg)

    async def move_channel(self, params: MoveChannelParams) -> ToolResult:
        """
        Move a channel to a different category.

        Args:
            params: Channel move parameters.

        Returns:
            ToolResult with success status.
        """
        self._log_action(f"Moving channel '{params.channel_name}'")

        has_perms, error = self._check_permissions("manage_channels")
        if not has_perms:
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.channel_name)
            if not channel:
                return ToolResult(
                    False,
                    f"Channel '{params.channel_name}' not found"
                )

            if isinstance(channel, CategoryChannel):
                return ToolResult(False, "Cannot move a category")

            category = None
            if params.category_name:
                category = self._find_channel_by_name(
                    params.category_name, CategoryChannel
                )
                if not category:
                    return ToolResult(
                        False,
                        f"Category '{params.category_name}' not found"
                    )

            await channel.edit(
                category=category,
                position=params.position,
                sync_permissions=params.sync_permissions,
            )

            dest = category.name if category else "no category"
            return ToolResult(
                True,
                f"Moved '{channel.name}' to {dest}",
            )

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to move channels")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")

    async def edit_channel(self, params: EditChannelParams) -> ToolResult:
        """
        Edit an existing channel's properties.

        Args:
            params: Channel edit parameters.

        Returns:
            ToolResult with success status.
        """
        self._log_action(f"Editing channel '{params.name}'")

        has_perms, error = self._check_permissions("manage_channels")
        if not has_perms:
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            channel = self._find_channel_by_name(params.name)
            if not channel:
                return ToolResult(False, f"Channel '{params.name}' not found")

            kwargs: dict[str, Any] = {}

            if params.new_name:
                kwargs["name"] = params.new_name

            if params.position is not None:
                kwargs["position"] = params.position

            # Text channel specific
            if isinstance(channel, TextChannel):
                if params.topic is not None:
                    kwargs["topic"] = params.topic
                if params.slowmode_delay is not None:
                    kwargs["slowmode_delay"] = params.slowmode_delay
                if params.nsfw is not None:
                    kwargs["nsfw"] = params.nsfw

            if not kwargs:
                return ToolResult(False, "No changes specified")

            await channel.edit(**kwargs)

            changes = ", ".join(kwargs.keys())
            return ToolResult(
                True,
                f"Edited channel '{params.name}': {changes}",
            )

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to edit channels")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")

    async def edit_role(self, params: EditRoleParams) -> ToolResult:
        """
        Edit an existing role's properties.

        Args:
            params: Role edit parameters.

        Returns:
            ToolResult with success status.
        """
        self._log_action(f"Editing role '{params.name}'")

        has_perms, error = self._check_permissions("manage_roles")
        if not has_perms:
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            role = self._find_role_by_name(params.name)
            if not role:
                return ToolResult(False, f"Role '{params.name}' not found")

            if not self._can_manage_role(role):
                return ToolResult(
                    False,
                    f"Cannot edit role '{params.name}' - it's higher than bot's role"
                )

            kwargs: dict[str, Any] = {}

            if params.new_name:
                kwargs["name"] = params.new_name

            if params.color:
                color = self._parse_color(params.color)
                if color:
                    kwargs["color"] = color

            if params.hoist is not None:
                kwargs["hoist"] = params.hoist

            if params.mentionable is not None:
                kwargs["mentionable"] = params.mentionable

            if params.position is not None:
                kwargs["position"] = params.position

            if params.permissions is not None:
                perms = discord.Permissions.none()
                for perm_name in params.permissions:
                    perm_name_lower = perm_name.lower()
                    if perm_name_lower in self.VALID_PERMISSIONS:
                        setattr(perms, perm_name_lower, True)
                kwargs["permissions"] = perms

            if not kwargs:
                return ToolResult(False, "No changes specified")

            await role.edit(**kwargs)

            changes = ", ".join(kwargs.keys())
            return ToolResult(
                True,
                f"Edited role '{params.name}': {changes}",
            )

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to edit roles")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")

    async def assign_role(self, params: AssignRoleParams) -> ToolResult:
        """
        Assign a role to a member.

        Args:
            params: Role assignment parameters.

        Returns:
            ToolResult with success status.
        """
        self._log_action(f"Assigning role '{params.role_name}' to '{params.member_name}'")

        has_perms, error = self._check_permissions("manage_roles")
        if not has_perms:
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            # Find member
            member = discord.utils.find(
                lambda m: (
                    m.name.lower() == params.member_name.lower()
                    or m.display_name.lower() == params.member_name.lower()
                ),
                self.guild.members,
            )
            if not member:
                return ToolResult(
                    False,
                    f"Member '{params.member_name}' not found"
                )

            role = self._find_role_by_name(params.role_name)
            if not role:
                return ToolResult(False, f"Role '{params.role_name}' not found")

            if not self._can_manage_role(role):
                return ToolResult(
                    False,
                    f"Cannot assign role '{params.role_name}' - it's higher than bot's role"
                )

            await member.add_roles(role, reason=params.reason)

            return ToolResult(
                True,
                f"Assigned role '{role.name}' to '{member.display_name}'",
            )

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to assign roles")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")

    async def remove_role(self, params: RemoveRoleParams) -> ToolResult:
        """
        Remove a role from a member.

        Args:
            params: Role removal parameters.

        Returns:
            ToolResult with success status.
        """
        self._log_action(f"Removing role '{params.role_name}' from '{params.member_name}'")

        has_perms, error = self._check_permissions("manage_roles")
        if not has_perms:
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            member = discord.utils.find(
                lambda m: (
                    m.name.lower() == params.member_name.lower()
                    or m.display_name.lower() == params.member_name.lower()
                ),
                self.guild.members,
            )
            if not member:
                return ToolResult(
                    False,
                    f"Member '{params.member_name}' not found"
                )

            role = self._find_role_by_name(params.role_name)
            if not role:
                return ToolResult(False, f"Role '{params.role_name}' not found")

            if not self._can_manage_role(role):
                return ToolResult(
                    False,
                    f"Cannot remove role '{params.role_name}' - it's higher than bot's role"
                )

            await member.remove_roles(role, reason=params.reason)

            return ToolResult(
                True,
                f"Removed role '{role.name}' from '{member.display_name}'",
            )

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to remove roles")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")

    async def bulk_create_roles(self, params: BulkCreateRolesParams) -> ToolResult:
        """
        Create multiple roles at once.

        Args:
            params: Bulk role creation parameters.

        Returns:
            ToolResult with created roles.
        """
        self._log_action(f"Bulk creating {len(params.roles)} roles")

        has_perms, error = self._check_permissions("manage_roles")
        if not has_perms:
            return ToolResult(False, error)

        try:
            created = []
            failed = []

            for role_config in params.roles:
                await self.rate_limiter.acquire()

                name = role_config.get("name", "New Role")
                color = self._parse_color(role_config.get("color")) or discord.Color.default()
                hoist = role_config.get("hoist", False)
                mentionable = role_config.get("mentionable", False)

                perms = discord.Permissions.none()
                for perm_name in role_config.get("permissions", []):
                    perm_name_lower = perm_name.lower()
                    if perm_name_lower in self.VALID_PERMISSIONS:
                        setattr(perms, perm_name_lower, True)

                try:
                    role = await self.guild.create_role(
                        name=name,
                        color=color,
                        hoist=hoist,
                        mentionable=mentionable,
                        permissions=perms,
                    )
                    created.append(role.name)
                except Exception as e:
                    failed.append(f"{name}: {str(e)}")

            msg = f"Created {len(created)} roles"
            if failed:
                msg += f". Failed: {len(failed)}"

            return ToolResult(
                True,
                msg,
                {"created": created, "failed": failed},
            )

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to create roles")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")

    async def clone_channel_permissions(
        self,
        params: CloneChannelPermissionsParams,
    ) -> ToolResult:
        """
        Clone permissions from one channel to another.

        Args:
            params: Clone parameters.

        Returns:
            ToolResult with success status.
        """
        self._log_action(
            f"Cloning permissions from '{params.source_channel}' to '{params.target_channel}'"
        )

        has_perms, error = self._check_permissions("manage_channels", "manage_roles")
        if not has_perms:
            return ToolResult(False, error)

        await self.rate_limiter.acquire()

        try:
            source = self._find_channel_by_name(params.source_channel)
            if not source:
                return ToolResult(
                    False,
                    f"Source channel '{params.source_channel}' not found"
                )

            target = self._find_channel_by_name(params.target_channel)
            if not target:
                return ToolResult(
                    False,
                    f"Target channel '{params.target_channel}' not found"
                )

            # Copy all permission overwrites
            count = 0
            for target_obj, overwrite in source.overwrites.items():
                await self.rate_limiter.batch_delay()
                await target.set_permissions(target_obj, overwrite=overwrite)
                count += 1

            return ToolResult(
                True,
                f"Cloned {count} permission overwrites from '{source.name}' to '{target.name}'",
            )

        except Forbidden:
            return ToolResult(False, "Bot lacks permission to clone permissions")
        except HTTPException as e:
            return ToolResult(False, f"Discord API error: {e.text}")


# ============================================================================
# Tool Factory Functions for Copilot SDK
# ============================================================================


def create_architect_tools(architect: DiscordArchitect) -> list:
    """
    Create Copilot SDK tool definitions for the Discord Architect.

    This function returns a list of tools that can be passed to the
    Copilot SDK session for function calling.

    Args:
        architect: The DiscordArchitect instance to wrap.

    Returns:
        List of tool definitions for the Copilot SDK.
    """
    from copilot import define_tool

    @define_tool(description="Create a new Discord channel (text, voice, or category)")
    async def create_channel(params: CreateChannelParams) -> str:
        """Create a channel in the Discord server."""
        result = await architect.create_channel(params)
        response = f"{'✅' if result.success else '❌'} {result.message}"
        if result.success and result.data:
            channel_id = result.data.get('channel_id')
            if channel_id:
                response += f" | Channel ID: {channel_id} | Mention: <#{channel_id}>"
        return response

    @define_tool(description="Create a new Discord role with optional permissions")
    async def create_role(params: CreateRoleParams) -> str:
        """Create a role in the Discord server."""
        result = await architect.create_role(params)
        response = f"{'✅' if result.success else '❌'} {result.message}"
        if result.success and result.data:
            role_id = result.data.get('role_id')
            if role_id:
                response += f" | Role ID: {role_id} | Mention: <@&{role_id}>"
        return response

    @define_tool(
        description="Set channel permissions for a specific role or member"
    )
    async def set_permissions(params: SetPermissionsParams) -> str:
        """Set channel-specific permissions."""
        logger.info(f"set_permissions tool invoked: channel='{params.channel_name}', target='{params.target_name}'")
        result = await architect.set_permissions(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Create a category with optional child channels"
    )
    async def create_category(params: CreateCategoryParams) -> str:
        """Create a category with optional channels."""
        result = await architect.create_category(params)
        response = f"{'✅' if result.success else '❌'} {result.message}"
        if result.success and result.data:
            cat_id = result.data.get('category_id')
            channels = result.data.get('channels', [])
            if cat_id:
                response += f" | Category ID: {cat_id}"
            if channels:
                channel_mentions = [f"<#{ch['id']}> ({ch['name']})" for ch in channels]
                response += f" | Channels: {', '.join(channel_mentions)}"
        return response

    @define_tool(
        description="Modify server settings like name, icon/logo, banner (boost level 2+), verification level, etc. Provide image URLs to set server icon or banner."
    )
    async def modify_server_settings(params: ModifyServerSettingsParams) -> str:
        """Modify guild-level settings."""
        result = await architect.modify_server_settings(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(description="Delete a channel from the server")
    async def delete_channel(params: DeleteChannelParams) -> str:
        """Delete a channel from the server."""
        result = await architect.delete_channel(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(description="Delete a role from the server")
    async def delete_role(params: DeleteRoleParams) -> str:
        """Delete a role from the server."""
        result = await architect.delete_role(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(description="Delete a category from the server, optionally deleting all channels inside it")
    async def delete_category(params: DeleteCategoryParams) -> str:
        """Delete a category from the server."""
        result = await architect.delete_category(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(description="Edit an existing category's name or position")
    async def edit_category(params: EditCategoryParams) -> str:
        """Edit category properties."""
        result = await architect.edit_category(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Get current server information including channels, roles, settings, description, features, and metadata. Use this to understand the server's purpose and tailor your configuration. Returns IDs that can be used for mentions: <#ID> for channels, <@&ID> for roles"
    )
    async def get_server_info() -> str:
        """Get server information."""
        result = await architect.get_server_info()
        if result.success:
            # Format with mention hints
            data = result.data
            lines = [f"**Server:** {data['name']} (ID: {data['id']})"]
            
            # Add description if available
            if data.get('description'):
                lines.append(f"**Description:** {data['description']}")
            
            lines.append(f"**Server Type:** {data.get('server_type', 'Standard Server')}")
            lines.append(f"**Members:** {data['member_count']} (Max: {data.get('max_members', 'Unknown')})")
            lines.append(f"**Verification:** {data['verification_level']}")
            lines.append(f"**Preferred Language:** {data.get('preferred_locale', 'en-US')}")
            
            # Boost information
            boost_level = data.get('boost_level', 0)
            boost_count = data.get('boost_count', 0)
            if boost_level > 0:
                lines.append(f"**Boost Status:** Level {boost_level} ({boost_count} boosts)")
            
            # Server features
            features = data.get('features', [])
            if features:
                # Show most relevant features
                important_features = [f for f in features if f in [
                    'COMMUNITY', 'PARTNERED', 'VERIFIED', 'DISCOVERABLE',
                    'WELCOME_SCREEN_ENABLED', 'THREADS_ENABLED', 'NEWS',
                    'ANIMATED_ICON', 'BANNER', 'VANITY_URL', 'COMMERCE'
                ]]
                if important_features:
                    lines.append(f"**Features:** {', '.join(important_features)}")
            
            lines.append("\n**Categories:**")
            for cat in data.get('categories', []):
                lines.append(f"  • {cat['name']} (ID: {cat['id']})")
            
            lines.append("\n**Text Channels:** (use <#ID> to mention)")
            for ch in data.get('text_channels', []):
                cat_info = f" in {ch['category']}" if ch.get('category') else ""
                lines.append(f"  • {ch['name']}{cat_info} | <#{ch['id']}>")
            
            lines.append("\n**Voice Channels:**")
            for ch in data.get('voice_channels', []):
                cat_info = f" in {ch['category']}" if ch.get('category') else ""
                lines.append(f"  • {ch['name']}{cat_info} | ID: {ch['id']}")
            
            lines.append("\n**Roles:** (use <@&ID> to mention)")
            for role in sorted(data.get('roles', []), key=lambda r: -r['position']):
                lines.append(f"  • {role['name']} ({role['color']}) | <@&{role['id']}>")
            
            # Add a note about using this info
            lines.append("\n💡 **Tip:** Use the server description, features, and existing structure to inform your design decisions.")
            
            return "\n".join(lines)
        return f"❌ {result.message}"

    # ========== Advanced Permission Tools ==========

    @define_tool(
        description="Set permissions on a category for multiple roles, optionally syncing to all child channels. Use for bulk permission updates like making a Staff category."
    )
    async def set_category_permissions(params: SetCategoryPermissionsParams) -> str:
        """Set category-wide permissions for roles."""
        logger.info(f"set_category_permissions tool invoked: category='{params.category_name}', roles={list(params.role_permissions.keys())}")
        result = await architect.set_category_permissions(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Make a channel private - hide it from @everyone and allow only specific roles to access it"
    )
    async def make_channel_private(params: MakeChannelPrivateParams) -> str:
        """Make a channel private to specific roles."""
        logger.info(f"make_channel_private tool invoked: channel='{params.channel_name}', allowed_roles={params.allowed_roles}")
        result = await architect.make_channel_private(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="🔧 AUTO-PERMISSION SUB-AGENT: Automatically configure permissions for ALL categories and channels in one call. Use this instead of manually setting permissions on each category. Templates: 'professional' (read-only info, member-only chat, staff-private), 'community' (open with moderation), 'private' (invite-only), 'gaming' (voice-focused). ALWAYS use this after creating categories to set up proper permissions."
    )
    async def auto_configure_permissions(params: AutoConfigurePermissionsParams) -> str:
        """Auto-configure all server permissions based on a template - acts as a sub-agent."""
        logger.info(f"auto_configure_permissions tool invoked: template='{params.template}', staff_roles={params.staff_roles}, info_categories={params.info_categories}, staff_categories={params.staff_categories}")
        result = await architect.auto_configure_permissions(params)
        if result.success and result.data:
            details = []
            if result.data.get("categories_updated"):
                details.append(f"Categories: {len(result.data['categories_updated'])}")
            if result.data.get("channels_updated"):
                details.append(f"Channels: {len(result.data['channels_updated'])}")
            if result.data.get("errors"):
                details.append(f"⚠️ Errors: {len(result.data['errors'])}")
            return f"{'✅' if result.success else '❌'} {result.message}\n📊 {' | '.join(details)}"
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Move an existing channel to a different category, optionally syncing permissions"
    )
    async def move_channel(params: MoveChannelParams) -> str:
        """Move a channel to a category."""
        result = await architect.move_channel(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Edit an existing channel's properties like name, topic, slowmode, NSFW status"
    )
    async def edit_channel(params: EditChannelParams) -> str:
        """Edit channel properties."""
        result = await architect.edit_channel(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Edit an existing role's properties like name, color, permissions, hoist, mentionable"
    )
    async def edit_role(params: EditRoleParams) -> str:
        """Edit role properties."""
        result = await architect.edit_role(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Assign a role to a server member"
    )
    async def assign_role(params: AssignRoleParams) -> str:
        """Assign a role to a member."""
        result = await architect.assign_role(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Remove a role from a server member"
    )
    async def remove_role(params: RemoveRoleParams) -> str:
        """Remove a role from a member."""
        result = await architect.remove_role(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Create multiple roles at once with their permissions and colors"
    )
    async def bulk_create_roles(params: BulkCreateRolesParams) -> str:
        """Create multiple roles at once."""
        result = await architect.bulk_create_roles(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Clone all permission overwrites from one channel to another"
    )
    async def clone_channel_permissions(params: CloneChannelPermissionsParams) -> str:
        """Clone permissions between channels."""
        result = await architect.clone_channel_permissions(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    # ========== Progress Tracking Tools ==========

    @define_tool(
        description="Set up the execution plan with a list of tasks. Call this FIRST before executing any tool. The plan will be shown to the user as a live-updating progress tracker."
    )
    async def set_plan(params: SetPlanParams) -> str:
        """Set up the execution plan for progress tracking."""
        architect.progress_tracker.set_plan(params.plan_title, params.tasks)
        await architect.progress_tracker.update_message()
        return f"✅ Plan set with {len(params.tasks)} tasks"

    @define_tool(
        description="Update a task's status in the progress tracker. Call this before and after each major operation to keep the user informed."
    )
    async def update_task(params: UpdateProgressParams) -> str:
        """Update task status in the progress tracker."""
        logger.info(f"update_task: task_id={params.task_id}, status={params.status}, details={params.details}")
        if params.status == "failed":
            logger.warning(f"Task {params.task_id} marked as FAILED: {params.details}")
        architect.progress_tracker.update_task(
            params.task_id,
            params.status,
            params.details,
        )
        await architect.progress_tracker.update_message()
        status_emoji = {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(params.status, "❓")
        return f"{status_emoji} Task {params.task_id} status: {params.status}"

    # ========== User Interaction Tools ==========

    @define_tool(
        description="Ask the user a question when you need clarification or input mid-task. Use this when you encounter ambiguous requirements, need to confirm destructive actions, or want user preference on design choices. The user will see a popup modal to answer."
    )
    async def ask_user(params: AskUserParams) -> str:
        """Ask the user a question and wait for their response."""
        result = await architect.ask_user(params)
        if result.success:
            return f"✅ User response: {result.data.get('answer', 'No answer')}"
        return f"❌ {result.message}"

    # ========== Design Reference Tools ==========

    @define_tool(
        description="**CALL THIS FIRST** when working on server design! Lists all available design sections including font styles (Script, Gothic, Sans-Serif, Serif, Special), decorative elements, templates, naming patterns, and more. Use this to see what's available, then fetch specific sections with get_design_section."
    )
    async def list_design_sections() -> str:
        """List all available design documentation sections."""
        import os
        logger.info("list_design_sections tool called")
        docs_path = os.path.join(os.path.dirname(__file__), "docs", "discord_design_guide.md")
        try:
            with open(docs_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Parse sections from the markdown
            sections = []
            current_section = None
            
            for line in content.split('\n'):
                # Main headers (# or ##)
                if line.startswith('### '):
                    # Subsections
                    subsection = line.replace('### ', '').strip()
                    if current_section:
                        sections.append(f"{current_section} > {subsection}")
                elif line.startswith('## '):
                    # Major sections
                    current_section = line.replace('## ', '').strip()
                    sections.append(current_section)
                elif line.startswith('# '):
                    # Title - skip
                    continue
            
            # Build categorized list
            result = ["✅ Available Design Sections:", ""]
            result.append("**Font Styles:**")
            result.append("  • Script/Cursive Fonts (Bold Script, Light Script)")
            result.append("  • Gothic/Fraktur Fonts (Gothic, Bold Fraktur)")
            result.append("  • Sans-Serif Fonts (Bold Sans, Italic Sans, Bold Italic Sans)")
            result.append("  • Serif Fonts (Bold Serif, Italic Serif, Bold Italic)")
            result.append("  • Special Style Fonts (Double-struck, Fullwidth, Monospace, Small Caps, Circled, etc.)")
            result.append("")
            result.append("**Design Elements:**")
            result.append("  • Separator & Line Characters")
            result.append("  • Aesthetic Decorative Elements")
            result.append("  • Emoji Guidelines by Channel Type")
            result.append("  • Role Color Palettes")
            result.append("")
            result.append("**Naming Patterns:**")
            result.append("  • Category Naming Patterns")
            result.append("  • Channel Naming Patterns")
            result.append("  • Server Description Formats")
            result.append("")
            result.append("**Complete Templates:**")
            result.append("  • Gaming Community Template")
            result.append("  • Aesthetic/Chill Template")
            result.append("  • Professional/Business Template")
            result.append("  • Development/Tech Template")
            result.append("  • AI/Tech Hub Template")
            result.append("  • Kawaii/Cute Template")
            result.append("")
            result.append("**Best Practices:**")
            result.append("  • Design Best Practices")
            result.append("")
            result.append("💡 Use `get_design_section` with section names like 'Script Fonts', 'Gaming Community Template', 'Emoji Guidelines', etc.")
            
            logger.info(f"Listed {len(sections)} design sections")
            return "\n".join(result)
            
        except FileNotFoundError:
            logger.warning("Design documentation file not found")
            return "❌ Design documentation not found at docs/discord_design_guide.md"
        except Exception as e:
            logger.error(f"Error loading design docs: {e}")
            return f"❌ Error loading design docs: {str(e)}"

    @define_tool(
        description="Get a specific section of the design documentation. Section names: 'Script Fonts', 'Gothic Fonts', 'Sans-Serif Fonts', 'Serif Fonts', 'Special Fonts', 'Separators', 'Decorative Elements', 'Category Patterns', 'Channel Patterns', 'Gaming Template', 'Professional Template', 'Tech Template', 'Aesthetic Template', 'Kawaii Template', 'Emoji Guidelines', 'Color Palettes', 'Description Formats', 'Best Practices', or 'All' for entire guide."
    )
    async def get_design_section(params: GetDesignSectionParams) -> str:
        """Fetch a specific section from the Discord design guide."""
        import os
        import re
        logger.info(f"get_design_section tool called - section: '{params.section}'")
        docs_path = os.path.join(os.path.dirname(__file__), "docs", "discord_design_guide.md")
        try:
            with open(docs_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            section_lower = params.section.lower()
            
            # Return full guide if requested
            if section_lower in ['all', 'full', 'complete', 'everything']:
                logger.info(f"Returning full design guide ({len(content)} characters)")
                return f"✅ Full Design Guide:\n\n{content}"
            
            # Define section patterns and their corresponding regex
            section_patterns = {
                'script': (r'### Script/Cursive Fonts.*?(?=###|\Z)', 'Script/Cursive Fonts'),
                'gothic': (r'### Gothic/Fraktur Fonts.*?(?=###|\Z)', 'Gothic/Fraktur Fonts'),
                'sans': (r'### Sans-Serif Fonts.*?(?=###|\Z)', 'Sans-Serif Fonts'),
                'serif': (r'### Serif Fonts.*?(?=###|\Z)', 'Serif Fonts'),
                'special': (r'### Special Style Fonts.*?(?=###|\Z)', 'Special Style Fonts'),
                'separator': (r'## Separator & Line Characters.*?(?=##|\Z)', 'Separators & Lines'),
                'decorative': (r'## Aesthetic Decorative Elements.*?(?=##|\Z)', 'Decorative Elements'),
                'category': (r'## Category Naming Patterns.*?(?=##|\Z)', 'Category Naming Patterns'),
                'channel': (r'## Channel Naming Patterns.*?(?=##|\Z)', 'Channel Naming Patterns'),
                'gaming': (r'### Gaming Community Template.*?(?=###|\Z)', 'Gaming Community Template'),
                'aesthetic': (r'### Aesthetic/Chill Template.*?(?=###|\Z)', 'Aesthetic/Chill Template'),
                'professional': (r'### Professional/Business Template.*?(?=###|\Z)', 'Professional/Business Template'),
                'tech': (r'### Development/Tech Template.*?(?=###|\Z)', 'Development/Tech Template'),
                'ai': (r'### AI/Tech Hub Template.*?(?=###|\Z)', 'AI/Tech Hub Template'),
                'kawaii': (r'### Kawaii/Cute Template.*?(?=###|\Z)', 'Kawaii/Cute Template'),
                'emoji': (r'## Emoji Guidelines by Channel Type.*?(?=##|\Z)', 'Emoji Guidelines'),
                'color': (r'## Role Color Palettes.*?(?=##|\Z)', 'Role Color Palettes'),
                'description': (r'## Server Description Formats.*?(?=##|\Z)', 'Server Description Formats'),
                'best': (r'## Design Best Practices.*?(?=##|\Z)', 'Design Best Practices'),
                'templates': (r'## Complete Server Templates.*?(?=##|\Z)', 'Complete Server Templates'),
            }
            
            # Find matching pattern
            for key, (pattern, display_name) in section_patterns.items():
                if key in section_lower or section_lower in display_name.lower():
                    match = re.search(pattern, content, re.DOTALL)
                    if match:
                        section_content = match.group(0).strip()
                        logger.info(f"Found section '{display_name}' ({len(section_content)} characters)")
                        return f"✅ {display_name}:\n\n{section_content}"
            
            # If no match found, try broader search
            lines = content.split('\n')
            section_start = None
            section_content_lines = []
            
            for i, line in enumerate(lines):
                if section_lower in line.lower():
                    if line.startswith('#'):
                        section_start = i
                        section_content_lines = [line]
                        continue
                
                if section_start is not None:
                    # Stop at next same-level or higher header
                    if line.startswith('#'):
                        header_level = len(line) - len(line.lstrip('#'))
                        start_level = len(lines[section_start]) - len(lines[section_start].lstrip('#'))
                        if header_level <= start_level:
                            break
                    section_content_lines.append(line)
            
            if section_content_lines:
                result = '\n'.join(section_content_lines).strip()
                logger.info(f"Found matching section ({len(result)} characters)")
                return f"✅ Section Match:\n\n{result}"
            
            # No match found
            logger.warning(f"Section '{params.section}' not found")
            return f"❌ Section '{params.section}' not found. Use `list_design_sections` to see available sections."
            
        except FileNotFoundError:
            logger.warning("Design documentation file not found")
            return "❌ Design documentation not found at docs/discord_design_guide.md"
        except Exception as e:
            logger.error(f"Error loading design section: {e}")
            return f"❌ Error loading design section: {str(e)}"

    # ========== Webhook & Embed Tools ==========

    @define_tool(
        description="Post a formatted embed message in a channel using a webhook. The embed is editable by the user later via the webhook URL. Use this for rules embeds, welcome messages, info panels, etc."
    )
    async def post_embed(params: PostWebhookEmbedParams) -> str:
        """Post an embed message via webhook."""
        result = await architect.post_webhook_embed(params)
        if result.success:
            return f"✅ {result.message}"
        return f"❌ {result.message}"

    @define_tool(
        description="Get the webhook URL for a channel. Users can use this URL to edit messages posted via the webhook."
    )
    async def get_webhook_url(params: GetWebhookParams) -> str:
        """Get the webhook URL for a channel."""
        result = await architect.get_channel_webhook(params)
        if result.success:
            return f"✅ {result.message}"
        return f"❌ {result.message}"

    @define_tool(
        description="Edit an existing embed message posted by the Envoy webhook. Requires the message_id from the original post_embed response."
    )
    async def edit_embed(params: EditWebhookMessageParams) -> str:
        """Edit an existing webhook embed message."""
        result = await architect.edit_webhook_message(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="Delete an embed message posted by the Envoy webhook. Requires the message_id."
    )
    async def delete_embed(params: DeleteWebhookMessageParams) -> str:
        """Delete a webhook embed message."""
        result = await architect.delete_webhook_message(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="List recent embed messages posted by the Envoy webhook in a channel. Use this to find message IDs for editing or deleting."
    )
    async def list_embed_messages(params: ListWebhookMessagesParams) -> str:
        """List webhook messages in a channel."""
        result = await architect.list_webhook_messages(params)
        return f"{'✅' if result.success else '❌'} {result.message}"

    @define_tool(
        description="**CALL THIS IF YOU CANT DO SOMETHING** if someone asks you to do a task outside your capabilities. Mark the task as complete with a summary of what was done instead of performing the action(s)."
    )
    async def mark_complete(params: MarkCompleteParams) -> str:
        """Mark a task as complete with a summary of what was done."""
        logger.info(f"Task marked complete: {params.summary}")
        # This is just a marker tool - the actual summary will be captured by the bot
        return f"✅ Task completed: {params.summary}"

    return [
        # Core channel/role operations
        create_channel,
        create_role,
        create_category,
        delete_channel,
        delete_role,
        delete_category,
        # Permission management
        set_permissions,
        set_category_permissions,
        make_channel_private,
        auto_configure_permissions,  # Sub-agent for bulk permission setup
        clone_channel_permissions,
        # Edit operations
        edit_channel,
        edit_role,
        move_channel,
        # Role assignment
        assign_role,
        remove_role,
        bulk_create_roles,
        # Server management
        modify_server_settings,
        get_server_info,
        # Progress tracking
        set_plan,
        update_task,
        # User interaction
        ask_user,
        mark_complete,
        # Design reference
        list_design_sections,
        get_design_section,
        # Webhook & embed
        post_embed,
        get_webhook_url,
        edit_embed,
        delete_embed,
        list_embed_messages,
    ]
