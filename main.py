"""
Envoy Discord Bot - Main Entry Point.

An agentic AI Discord bot designed to autonomously configure and manage
Discord servers based on natural language commands using the GitHub Copilot SDK.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

import discord
import yaml
from discord import app_commands, Interaction
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import re

from architect import (
    DiscordArchitect,
    ExecutionPlan,
    PlanAction,
    RateLimiter,
    create_architect_tools,
)

# ============================================================================
# Configuration Loading
# ============================================================================


def load_config(config_path: str = "config.yml") -> dict[str, Any]:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to the configuration file.

    Returns:
        Configuration dictionary.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            "Please create a config.yml file based on config.yml.example"
        )

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Validate required fields
    if not config.get("discord", {}).get("token"):
        raise ValueError("Discord token not found in config.yml")

    return config


# ============================================================================
# Logging Setup
# ============================================================================


def setup_logging(config: dict[str, Any]) -> logging.Logger:
    """
    Set up logging based on configuration.

    Args:
        config: Logging configuration dictionary.

    Returns:
        Configured logger instance.
    """
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper())
    log_file = log_config.get("file", "logs/envoy.log")
    log_format = log_config.get(
        "format",
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    max_size = log_config.get("max_size_mb", 10) * 1024 * 1024
    backup_count = log_config.get("backup_count", 5)

    # Create logs directory if needed
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    logger = logging.getLogger("envoy")
    logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(console_handler)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_size,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)

    return logger


# ============================================================================
# Guild Configuration Manager (Persistent Per-Server Config)
# ============================================================================


class GuildConfigManager:
    """
    Manages persistent per-server configuration including allowlists.
    
    Stores configuration in a JSON file with guild IDs as keys.
    """

    def __init__(self, config_path: str = "data/guild_configs.json"):
        """
        Initialize the guild config manager.

        Args:
            config_path: Path to the JSON configuration file.
        """
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._configs: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load configurations from disk."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._configs = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._configs = {}
        else:
            self._configs = {}

    def _save(self) -> None:
        """Save configurations to disk."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._configs, f, indent=2)

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create config for a guild."""
        key = str(guild_id)
        if key not in self._configs:
            self._configs[key] = {
                "allowlist": [],  # User IDs allowed to use /architect
                "settings": {},   # Future: other per-server settings
            }
        return self._configs[key]

    def is_allowed(self, guild_id: int, user_id: int, owner_id: int) -> bool:
        """
        Check if a user is allowed to use /architect.
        
        Args:
            guild_id: The Discord guild ID.
            user_id: The user attempting to use the command.
            owner_id: The guild owner's ID (always allowed).
            
        Returns:
            True if the user is the owner or on the allowlist.
        """
        if user_id == owner_id:
            return True
        config = self._get_guild_config(guild_id)
        return user_id in config["allowlist"]

    def add_to_allowlist(self, guild_id: int, user_id: int) -> bool:
        """
        Add a user to the allowlist.
        
        Returns:
            True if user was added, False if already on list.
        """
        config = self._get_guild_config(guild_id)
        if user_id not in config["allowlist"]:
            config["allowlist"].append(user_id)
            self._save()
            return True
        return False

    def remove_from_allowlist(self, guild_id: int, user_id: int) -> bool:
        """
        Remove a user from the allowlist.
        
        Returns:
            True if user was removed, False if not on list.
        """
        config = self._get_guild_config(guild_id)
        if user_id in config["allowlist"]:
            config["allowlist"].remove(user_id)
            self._save()
            return True
        return False

    def get_allowlist(self, guild_id: int) -> list[int]:
        """Get the allowlist for a guild."""
        config = self._get_guild_config(guild_id)
        return config["allowlist"].copy()


# ============================================================================
# User Rate Limit Manager (Per-User Usage Quotas)
# ============================================================================


class UserRateLimitManager:
    """
    Manages per-user daily usage quotas for API cost control.
    
    Tracks usage in a JSON file with user IDs as keys.
    Quotas reset daily at midnight UTC.
    """

    def __init__(
        self,
        config_path: str = "data/user_quotas.json",
        architect_limit: int = 1,
        continuation_limit: int = 10,
    ):
        """
        Initialize the user rate limit manager.

        Args:
            config_path: Path to the JSON quota file.
            architect_limit: Max /architect commands per day per user.
            continuation_limit: Max continuation replies per day per user.
        """
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.architect_limit = architect_limit
        self.continuation_limit = continuation_limit
        self._usage: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load usage data from disk."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._usage = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._usage = {}
        else:
            self._usage = {}

    def _save(self) -> None:
        """Save usage data to disk."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._usage, f, indent=2)

    def _get_reset_timestamp(self) -> float:
        """Get the next midnight UTC timestamp for quota reset."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
        return tomorrow.timestamp()

    def _get_today_key(self) -> str:
        """Get today's date key in YYYY-MM-DD format."""
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def _get_user_usage(self, user_id: int) -> dict:
        """Get or create usage record for a user."""
        key = str(user_id)
        today = self._get_today_key()
        
        if key not in self._usage:
            self._usage[key] = {
                "date": today,
                "architect_count": 0,
                "continuation_count": 0,
            }
        
        # Reset if it's a new day
        if self._usage[key].get("date") != today:
            self._usage[key] = {
                "date": today,
                "architect_count": 0,
                "continuation_count": 0,
            }
            self._save()
        
        return self._usage[key]

    def check_architect_quota(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        Check if user can use /architect command.
        
        Returns:
            Tuple of (allowed: bool, error_message: Optional[str])
            If not allowed, error_message contains the formatted response with Discord timestamps.
        """
        usage = self._get_user_usage(user_id)
        
        if usage["architect_count"] >= self.architect_limit:
            reset_ts = int(self._get_reset_timestamp())
            return (
                False,
                f"❌ **Usage Quota Exceeded**\n\n"
                f"You've used your daily `/architect` command.\n\n"
                f"**Limit:** {self.architect_limit} per day\n"
                f"**Resets:** <t:{reset_ts}:R> (<t:{reset_ts}:F>)\n\n"
                f"💡 You can still use up to {self.continuation_limit - usage['continuation_count']} reply continuations today."
            )
        
        return (True, None)

    def check_continuation_quota(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        Check if user can use continuation (reply) feature.
        
        Returns:
            Tuple of (allowed: bool, error_message: Optional[str])
        """
        usage = self._get_user_usage(user_id)
        
        if usage["continuation_count"] >= self.continuation_limit:
            reset_ts = int(self._get_reset_timestamp())
            return (
                False,
                f"❌ **Usage Quota Exceeded**\n\n"
                f"You've used all your daily reply continuations.\n\n"
                f"**Limit:** {self.continuation_limit} continuations per day\n"
                f"**Resets:** <t:{reset_ts}:R> (<t:{reset_ts}:F>)\n\n"
                f"💡 Try again tomorrow!"
            )
        
        return (True, None)

    def use_architect(self, user_id: int) -> None:
        """Record usage of /architect command."""
        usage = self._get_user_usage(user_id)
        usage["architect_count"] += 1
        self._save()

    def use_continuation(self, user_id: int) -> None:
        """Record usage of continuation reply."""
        usage = self._get_user_usage(user_id)
        usage["continuation_count"] += 1
        self._save()

    def get_usage_stats(self, user_id: int) -> dict:
        """Get usage stats for a user."""
        usage = self._get_user_usage(user_id)
        reset_ts = int(self._get_reset_timestamp())
        return {
            "architect_used": usage["architect_count"],
            "architect_limit": self.architect_limit,
            "architect_remaining": max(0, self.architect_limit - usage["architect_count"]),
            "continuation_used": usage["continuation_count"],
            "continuation_limit": self.continuation_limit,
            "continuation_remaining": max(0, self.continuation_limit - usage["continuation_count"]),
            "reset_timestamp": reset_ts,
        }


# ============================================================================
# Confirmation View (Discord UI)
# ============================================================================


class PlanConfirmationView(View):
    """Discord UI view for confirming or canceling an execution plan."""

    def __init__(
        self,
        timeout: float = 300.0,
        author_id: int | None = None,
    ):
        """
        Initialize the confirmation view.

        Args:
            timeout: Timeout in seconds before the view expires.
            author_id: ID of the user who can interact with the buttons.
        """
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed: Optional[bool] = None
        self.feedback: Optional[str] = None  # User's feedback for plan revision
        self.event = asyncio.Event()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Check if the user can interact with the buttons."""
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the command author can confirm or cancel this plan.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def confirm_button(
        self,
        interaction: Interaction,
        button: Button,
    ) -> None:
        """Handle confirm button click."""
        self.confirmed = True
        self.event.set()
        # Update embed to show confirmed state
        confirmed_embed = discord.Embed(
            title="✅ Plan Confirmed",
            description="Executing your plan now...",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(
            content=None,
            embed=confirmed_embed,
            view=None,
        )
        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel_button(
        self,
        interaction: Interaction,
        button: Button,
    ) -> None:
        """Handle cancel button click."""
        self.confirmed = False
        # Update embed to show cancelled state
        cancelled_embed = discord.Embed(
            title="✖️ Plan Cancelled",
            description="No changes were made to your server.",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(
            content=None,
            embed=cancelled_embed,
            view=None,
        )
        self.event.set()
        self.stop()

    @discord.ui.button(
        label="Suggest Changes",
        style=discord.ButtonStyle.primary,
        emoji="💬",
    )
    async def feedback_button(
        self,
        interaction: Interaction,
        button: Button,
    ) -> None:
        """Handle feedback button click - opens modal for plan revision suggestions."""
        modal = PlanFeedbackModal()
        await interaction.response.send_modal(modal)
        
        # Wait for modal submission
        try:
            await asyncio.wait_for(modal.submitted.wait(), timeout=300.0)
            if modal.feedback_text:
                self.feedback = modal.feedback_text
                self.confirmed = None  # Neither confirmed nor cancelled - revision requested
                
                # Update embed to show revision state
                revision_embed = discord.Embed(
                    title="💬 Revising Plan...",
                    description=f"**Your feedback:**\n{modal.feedback_text[:500]}\n\nGenerating revised plan...",
                    color=discord.Color.blue(),
                )
                await interaction.message.edit(embed=revision_embed, view=None)
                self.event.set()
                self.stop()
        except asyncio.TimeoutError:
            pass  # Modal timed out, don't do anything

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        self.confirmed = False
        self.event.set()


class PlanFeedbackModal(Modal):
    """Modal for providing feedback on a proposed plan."""

    def __init__(self):
        super().__init__(title="Suggest Changes to Plan")
        self.feedback_text: Optional[str] = None
        self.submitted = asyncio.Event()

        self.feedback_input = TextInput(
            label="What would you like to change?",
            style=discord.TextStyle.paragraph,
            placeholder="e.g., 'Use different colors', 'Add more voice channels', 'Rename the Admin role to Moderator'...",
            required=True,
            max_length=1000,
        )
        self.add_item(self.feedback_input)

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        self.feedback_text = self.feedback_input.value
        self.submitted.set()
        await interaction.response.send_message(
            "✅ Got your feedback! Revising the plan...",
            ephemeral=True,
        )


# ============================================================================
# Continuation Confirmation View (for follow-up plan execution)
# ============================================================================


class ContinuationConfirmView(View):
    """
    Discord UI view for confirming continuation plans.
    
    This view is attached to continuation responses that propose changes,
    allowing users to confirm execution with a button click.
    """

    def __init__(
        self,
        bot: "EnvoyBot",
        message: discord.Message,
        guild_id: int,
        proposed_plan: str,
        timeout: float = 300.0,
    ):
        """
        Initialize the continuation confirmation view.

        Args:
            bot: The EnvoyBot instance for executing the plan.
            message: The original user message that triggered the continuation.
            guild_id: The guild ID for context.
            proposed_plan: The AI's proposed plan text.
            timeout: Timeout in seconds before the view expires.
        """
        super().__init__(timeout=timeout)
        self.bot = bot
        self.original_message = message
        self.guild_id = guild_id
        self.proposed_plan = proposed_plan
        self.author_id = message.author.id

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Check if the user can interact with the buttons."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the original requester can confirm or cancel this plan.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Execute",
        style=discord.ButtonStyle.success,
        emoji="▶️",
    )
    async def execute_button(
        self,
        interaction: Interaction,
        button: Button,
    ) -> None:
        """Handle execute button click - runs the proposed plan."""
        # Update embed to show executing state
        executing_embed = discord.Embed(
            title="⚡ Executing Plan...",
            description="Please wait while I make the changes.",
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=executing_embed, view=None)

        try:
            # Get context
            context = self.bot._session_contexts.get(self.guild_id, {})
            previous_actions = context.get("actions", [])

            # Get or create architect
            architect = self.bot._architects.get(self.guild_id)
            if not architect:
                architect = DiscordArchitect(
                    interaction.guild,
                    RateLimiter(
                        self.bot.config.get("rate_limits", {}).get("batch_delay", 1.0)
                    ),
                )
                self.bot._architects[self.guild_id] = architect

            # Build execution prompt
            context_summary = ""
            if previous_actions:
                recent_actions = previous_actions[-10:]
                context_summary = (
                    f"\n\n**Previous actions:**\n"
                    + "\n".join(f"• {a}" for a in recent_actions)
                )

            execution_prompt = (
                f"**USER CONFIRMED EXECUTION**\n\n"
                f"Your proposed plan was:\n{self.proposed_plan[:2500]}\n\n"
                f"{context_summary}\n\n"
                "The user clicked the Execute button. IMMEDIATELY call the tools to "
                "execute this plan NOW. Do not ask for confirmation - just do it. "
                "Execute each step, then provide a brief summary of what was completed."
            )

            # Create session and execute
            tools = create_architect_tools(architect)
            system_message = self.bot.config.get("ai", {}).get("system_message", "")
            model = self.bot.config.get("ai", {}).get("model", "gpt-4")

            session = await self.bot._copilot_client.create_session({
                "model": model,
                "streaming": True,
                "tools": tools,
                "system_message": {"content": system_message} if system_message else None,
            })

            response_chunks: list[str] = []
            done_event = asyncio.Event()

            def on_event(event):
                event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
                if event_type == "assistant.message_delta":
                    delta = event.data.delta_content or ""
                    response_chunks.append(delta)
                elif event_type == "session.idle":
                    done_event.set()

            session.on(on_event)
            await session.send({"prompt": execution_prompt})

            try:
                await asyncio.wait_for(done_event.wait(), timeout=180.0)
            except asyncio.TimeoutError:
                error_embed = discord.Embed(
                    title="⏰ Execution Timed Out",
                    description="The operation took too long. Some changes may have been applied.",
                    color=discord.Color.orange(),
                )
                await interaction.message.edit(embed=error_embed)
                await session.destroy()
                return

            full_response = "".join(response_chunks)
            if len(full_response) > 4000:
                full_response = full_response[:4000] + "\n\n*(truncated)*"

            # Create completion embed
            completion_embed = discord.Embed(
                title="✅ Plan Executed",
                description=full_response if full_response else "Changes applied successfully!",
                color=discord.Color.green(),
            )
            completion_embed.set_footer(text="Reply to this message to continue")

            await interaction.message.edit(embed=completion_embed)

            # Track this message for continuations
            self.bot._summary_messages[interaction.message.id] = self.guild_id

            # Update context
            if self.guild_id not in self.bot._session_contexts:
                self.bot._session_contexts[self.guild_id] = {"actions": [], "last_response": ""}
            
            exec_log = architect.get_execution_log()
            if exec_log:
                formatted_actions = [f"{msg} {'(failed)' if not success else ''}".strip() for msg, success in exec_log]
                self.bot._session_contexts[self.guild_id]["actions"].extend(formatted_actions)
            self.bot._session_contexts[self.guild_id]["last_response"] = full_response

            await session.destroy()

        except Exception as e:
            self.bot.logger.exception(f"Error executing continuation plan: {e}")
            error_embed = discord.Embed(
                title="❌ Execution Failed",
                description=f"An error occurred: {str(e)}",
                color=discord.Color.red(),
            )
            await interaction.message.edit(embed=error_embed)

        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel_button(
        self,
        interaction: Interaction,
        button: Button,
    ) -> None:
        """Handle cancel button click."""
        cancelled_embed = discord.Embed(
            title="✖️ Plan Cancelled",
            description="No changes were made. Reply to continue with a different request.",
            color=discord.Color.light_grey(),
        )
        cancelled_embed.set_footer(text="Reply to this message to continue")
        await interaction.response.edit_message(embed=cancelled_embed, view=None)
        
        # Still track for continuations
        self.bot._summary_messages[interaction.message.id] = self.guild_id
        self.stop()

    @discord.ui.button(
        label="Suggest Changes",
        style=discord.ButtonStyle.primary,
        emoji="💬",
    )
    async def feedback_button(
        self,
        interaction: Interaction,
        button: Button,
    ) -> None:
        """Handle feedback button click - revise the proposed plan."""
        modal = PlanFeedbackModal()
        await interaction.response.send_modal(modal)
        
        # Wait for modal submission
        try:
            await asyncio.wait_for(modal.submitted.wait(), timeout=300.0)
            if modal.feedback_text:
                # Update embed to show revising state
                revising_embed = discord.Embed(
                    title="💬 Revising Plan...",
                    description=f"**Your feedback:**\n{modal.feedback_text[:500]}\n\nGenerating revised plan...",
                    color=discord.Color.blue(),
                )
                await interaction.message.edit(embed=revising_embed, view=None)

                try:
                    # Get or create architect
                    architect = self.bot._architects.get(self.guild_id)
                    if not architect:
                        architect = DiscordArchitect(
                            interaction.guild,
                            RateLimiter(
                                self.bot.config.get("rate_limits", {}).get("batch_delay", 1.0)
                            ),
                        )
                        self.bot._architects[self.guild_id] = architect

                    # Create session for revision
                    tools = create_architect_tools(architect)
                    system_message = self.bot.config.get("ai", {}).get("system_message", "")
                    model = self.bot.config.get("ai", {}).get("model", "gpt-4")

                    session = await self.bot._copilot_client.create_session({
                        "model": model,
                        "streaming": True,
                        "tools": tools,
                        "system_message": {"content": system_message} if system_message else None,
                    })

                    response_chunks: list[str] = []
                    done_event = asyncio.Event()

                    def on_event(event):
                        event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
                        if event_type == "assistant.message_delta":
                            delta = event.data.delta_content or ""
                            response_chunks.append(delta)
                        elif event_type == "session.idle":
                            done_event.set()

                    session.on(on_event)

                    revision_prompt = (
                        f"The user wants changes to your proposed plan.\n\n"
                        f"**User feedback:**\n{modal.feedback_text}\n\n"
                        f"**Previous plan:**\n{self.proposed_plan[:2000]}\n\n"
                        "Please revise your plan based on this feedback. "
                        "Use the same format as before:\n\n"
                        "**What I'll Do:**\n"
                        "✦ [Simple action description]\n\n"
                        "**Details:**\n"
                        "• [Category/role/channel names]\n\n"
                        "⚠️ [Any warnings]\n\n"
                        "NEVER show: function names, tool calls, parameters, code."
                    )

                    await session.send({"prompt": revision_prompt})

                    try:
                        await asyncio.wait_for(done_event.wait(), timeout=120.0)
                    except asyncio.TimeoutError:
                        error_embed = discord.Embed(
                            title="⏰ Revision Timed Out",
                            description="Please try again by replying to this message.",
                            color=discord.Color.orange(),
                        )
                        await interaction.message.edit(embed=error_embed)
                        await session.destroy()
                        self.stop()
                        return

                    full_response = "".join(response_chunks)
                    if len(full_response) > 4000:
                        full_response = full_response[:4000] + "\n\n*(truncated)*"

                    # Create new view with revised plan
                    new_view = ContinuationConfirmView(
                        bot=self.bot,
                        message=self.original_message,
                        guild_id=self.guild_id,
                        proposed_plan=full_response,
                    )

                    revised_embed = discord.Embed(
                        title="📋 Revised Plan",
                        description=full_response,
                        color=discord.Color.gold(),
                    )
                    revised_embed.set_footer(text="Click Execute to apply, Cancel to skip, or Suggest Changes")

                    await interaction.message.edit(embed=revised_embed, view=new_view)
                    await session.destroy()

                except Exception as e:
                    self.bot.logger.exception(f"Error revising plan: {e}")
                    error_embed = discord.Embed(
                        title="❌ Revision Failed",
                        description=f"An error occurred: {str(e)}\n\nReply to this message to try again.",
                        color=discord.Color.red(),
                    )
                    await interaction.message.edit(embed=error_embed)

                self.stop()
        except asyncio.TimeoutError:
            pass  # Modal timed out

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        try:
            # Try to update the message to show it expired
            timeout_embed = discord.Embed(
                title="⏰ Confirmation Expired",
                description="The confirmation timed out. Reply to this message to try again.",
                color=discord.Color.dark_grey(),
            )
            # Note: We can't easily edit the message here without storing it
            pass
        except Exception:
            pass


# ============================================================================
# Question Modal and View (for AI asking user questions)
# ============================================================================


class QuestionModal(Modal):
    """Modal popup for answering AI questions."""

    def __init__(
        self,
        question: str,
        context: Optional[str] = None,
        options: Optional[list[str]] = None,
    ):
        """
        Initialize the question modal.

        Args:
            question: The AI's question to the user.
            context: Optional context about why the question is being asked.
            options: Optional list of suggested answers.
        """
        super().__init__(title="🤖 Envoy needs your input")
        self.answer: Optional[str] = None
        self.answered = asyncio.Event()

        # Build the label with question (max 45 chars for label)
        label = question[:45] if len(question) <= 45 else question[:42] + "..."

        # Build the placeholder with options if provided
        placeholder = "Type your answer here..."
        if options:
            placeholder = f"Suggestions: {', '.join(options[:3])}"

        # Create the text input
        self.answer_input = TextInput(
            label=label,
            style=discord.TextStyle.paragraph,
            placeholder=placeholder,
            required=True,
            max_length=500,
        )
        self.add_item(self.answer_input)

        # If the question is longer, we'll show the full question in the modal title/description
        self.full_question = question
        self.context = context

    async def on_submit(self, interaction: Interaction) -> None:
        """Handle modal submission."""
        self.answer = self.answer_input.value
        self.answered.set()
        
        await interaction.response.send_message(
            f"✅ Got it! Your answer: **{self.answer}**\n\nContinuing execution...",
            ephemeral=True,
        )


class QuestionView(View):
    """View with a button that opens the question modal."""

    def __init__(
        self,
        question: str,
        context: Optional[str] = None,
        options: Optional[list[str]] = None,
        author_id: Optional[int] = None,
        timeout: float = 300.0,
    ):
        """
        Initialize the question view.

        Args:
            question: The AI's question.
            context: Optional context about why the question is being asked.
            options: Optional list of suggested answers.
            author_id: ID of the user who can answer.
            timeout: Timeout in seconds.
        """
        super().__init__(timeout=timeout)
        self.question = question
        self.context = context
        self.options = options
        self.author_id = author_id
        self.answer: Optional[str] = None
        self.answered = asyncio.Event()
        self.timed_out = False

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Check if the user can interact with the button."""
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the command author can answer this question.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Answer Question",
        style=discord.ButtonStyle.primary,
        emoji="💬",
    )
    async def answer_button(
        self,
        interaction: Interaction,
        button: Button,
    ) -> None:
        """Handle answer button click - opens modal."""
        modal = QuestionModal(
            question=self.question,
            context=self.context,
            options=self.options,
        )
        await interaction.response.send_modal(modal)
        
        # Wait for the modal to be answered
        try:
            await asyncio.wait_for(modal.answered.wait(), timeout=300.0)
            self.answer = modal.answer
            self.answered.set()
            self.stop()
        except asyncio.TimeoutError:
            self.timed_out = True
            self.answered.set()
            self.stop()

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        self.timed_out = True
        self.answered.set()


# ============================================================================
# Envoy Bot Class
# ============================================================================


class EnvoyBot(commands.Bot):
    """
    The Envoy Discord bot for autonomous server configuration.

    This bot uses the GitHub Copilot SDK to interpret natural language
    commands and execute Discord API operations through defined tools.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize the Envoy bot.

        Args:
            config: Configuration dictionary loaded from config.yml.
        """
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True

        prefix = config.get("discord", {}).get("prefix", "!")

        super().__init__(
            command_prefix=prefix,
            intents=intents,
            help_command=None,
        )

        self.config = config
        self.logger = logging.getLogger("envoy.bot")
        self._copilot_client = None
        self._architects: dict[int, DiscordArchitect] = {}
        # Context storage for agentic continuation (guild_id -> session context)
        # Structure: {"actions": [tool logs], "changes": [{"request": str, "summary": str, "timestamp": float}], "last_response": str}
        self._session_contexts: dict[int, dict] = {}
        # Track summary messages for reply detection (message_id -> guild_id)
        self._summary_messages: dict[int, int] = {}
        # Per-server configuration manager
        self._guild_configs = GuildConfigManager()
        # Per-user rate limit manager
        quota_config = config.get("user_quotas", {})
        self._user_quotas = UserRateLimitManager(
            architect_limit=quota_config.get("architect_per_day", 1),
            continuation_limit=quota_config.get("continuations_per_day", 10),
        )

        # Patterns for prohibited content (hate/extremism, blatant racism, nazism, KKK, slurs, NSFW, etc.)
        self._prohibited_patterns: list[re.Pattern] = [
            re.compile(r"\bnazi\b", re.I),
            re.compile(r"\bswastika\b", re.I),
            re.compile(r"\bwhite\s*supremac", re.I),
            re.compile(r"\bkkk\b", re.I),
            re.compile(r"\bracist\b", re.I),
            re.compile(r"\bracism\b", re.I),
            re.compile(r"\bextremist\b", re.I),
            re.compile(r"\bholocaust\b", re.I),
            re.compile(r"\bnazi\w*\b", re.I),
            re.compile(r"\bnsfw\b", re.I),
            re.compile(r"\bsex\b", re.I),
        ]

    def contains_prohibited_content(self, text: str) -> Optional[str]:
        """Return a matching pattern name if text contains prohibited content, otherwise None."""
        if not text:
            return None
        for pat in self._prohibited_patterns:
            match = pat.search(text)
            if match:
                self.logger.debug(f"Prohibited content matched: pattern={pat.pattern}, matched_text='{match.group()}'")
                return pat.pattern
        return None

    async def setup_hook(self) -> None:
        """Set up the bot before it starts."""
        self.logger.info("Setting up Envoy bot...")

        # Initialize Copilot SDK client
        try:
            from copilot import CopilotClient

            self._copilot_client = CopilotClient()
            await self._copilot_client.start()
            self.logger.info("Copilot SDK client initialized")
        except ImportError:
            self.logger.error(
                "github-copilot-sdk not installed. "
                "Run: pip install github-copilot-sdk"
            )
            raise
        except Exception as e:
            self.logger.error(f"Failed to initialize Copilot client: {e}")
            raise

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"Synced {len(synced)} slash commands")
        except Exception as e:
            self.logger.error(f"Failed to sync commands: {e}")

    async def close(self) -> None:
        """Clean up resources when the bot shuts down."""
        self.logger.info("Shutting down Envoy bot...")

        if self._copilot_client:
            try:
                await self._copilot_client.stop()
            except Exception as e:
                self.logger.error(f"Error stopping Copilot client: {e}")

        await super().close()

    async def on_ready(self) -> None:
        """Handle bot ready event."""
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        self.logger.info(f"Connected to {len(self.guilds)} guilds")

        # Set presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for /architect commands",
            )
        )

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages, including replies to summary messages."""
        # Ignore bot messages
        if message.author.bot:
            return

        self.logger.debug(
            f"on_message: author={message.author.name}, is_reference={bool(message.reference)}, "
            f"content_preview='{message.content[:50] if message.content else '(empty)'}'"
        )

        # Check if this is a reply to a summary message
        if message.reference and message.reference.message_id:
            ref_id = message.reference.message_id
            self.logger.debug(f"Message is a reply to message ID: {ref_id}. Checking if it's a tracked summary...")
            
            # Check if the referenced message is a tracked summary message
            if ref_id in self._summary_messages:
                guild_id = self._summary_messages[ref_id]
                self.logger.debug(f"Found tracked summary for guild {guild_id}. Message content: '{message.content[:100]}'")
                
                # Verify it's the same guild
                self.logger.debug(
                    f"Guild verification: message.guild={message.guild}, "
                    f"message.guild.id={message.guild.id if message.guild else 'None'}, "
                    f"expected_guild_id={guild_id}, "
                    f"match={message.guild and message.guild.id == guild_id}"
                )
                
                if message.guild and message.guild.id == guild_id:
                    # Check if user is authorized (owner or on allowlist)
                    is_authorized = self._guild_configs.is_allowed(
                        message.guild.id, message.author.id, message.guild.owner_id
                    )
                    self.logger.debug(
                        f"Continuation auth check: user={message.author.id}, guild={message.guild.id}, "
                        f"owner={message.guild.owner_id}, authorized={is_authorized}"
                    )
                    
                    if not is_authorized:
                        await message.reply(
                            "Only the server owner or users on the allowlist can continue configurations via reply.",
                            mention_author=False,
                        )
                        return
                    
                    # Process as continuation request
                    self.logger.info(f"Processing continuation from authorized user: {message.author}")
                    await self.process_continuation(message, guild_id)
                    return
                else:
                    self.logger.warning(
                        f"Guild verification FAILED for continuation reply. "
                        f"message.guild={message.guild}, expected_guild={guild_id}"
                    )
            else:
                self.logger.debug(
                    f"Reply ref_id {ref_id} not found in tracked summaries. "
                    f"Known summaries: {list(self._summary_messages.keys())}"
                )

        # Process other commands
        await self.process_commands(message)

    async def process_continuation(
        self,
        message: discord.Message,
        guild_id: int,
    ) -> None:
        """
        Process a continuation request from a reply to a summary message.

        Args:
            message: The reply message containing the continuation request.
            guild_id: The guild ID for context.
        """
        # Check user quota
        allowed, error_msg = self._user_quotas.check_continuation_quota(message.author.id)
        if not allowed:
            await message.reply(error_msg, mention_author=False)
            return

        # Pre-check continuation content for prohibited terms
        matched = self.contains_prohibited_content(message.content)
        if matched:
            self.logger.warning(
                f"Prohibited continuation blocked from {message.author} in {message.guild.name}: {message.content}"
            )
            await message.reply(
                "❌ I can't assist with creating or organizing hateful, extremist, or sexually explicit/NSFW servers or content. "
                "If you need help with moderation, safety, or non-NSFW community setups, I can help with that.",
                mention_author=False,
            )
            return

        # Record usage
        self._user_quotas.use_continuation(message.author.id)

        self.logger.info(
            f"Continuation request from {message.author} in {message.guild.name}: {message.content}"
        )

        # Get existing context
        context = self._session_contexts.get(guild_id, {})
        previous_actions = context.get("actions", [])

        # Show typing indicator
        async with message.channel.typing():
            try:
                # Get or create architect
                architect = self._architects.get(guild_id)
                if not architect:
                    architect = DiscordArchitect(
                        message.guild,
                        RateLimiter(
                            self.config.get("rate_limits", {}).get("batch_delay", 1.0)
                        ),
                    )
                    self._architects[guild_id] = architect

                # Build context-aware prompt with meaningful change history
                context_summary = ""
                
                # Get previous meaningful changes (not just tool logs)
                previous_changes = context.get("changes", [])
                if previous_changes:
                    recent_changes = previous_changes[-5:]  # Last 5 requests with their results
                    context_summary = "\n\n**Session History (what I did previously):**\n"
                    for i, change in enumerate(recent_changes, 1):
                        context_summary += f"{i}. **Request:** {change['request'][:100]}\n"
                        context_summary += f"   **What I did:** {change['summary'][:200]}\n\n"
                    context_summary += "Use this history to understand context like 'change it back' or 'undo that'.\n"

                # Build the prompt - encourage direct execution for clear requests
                enhanced_prompt = (
                    f"User request (continuation): {message.content}"
                    f"{context_summary}\n\n"
                    "The user is continuing from a previous session.\n\n"
                    "**WORKFLOW:**\n"
                    "1. Call get_server_info() to see current state\n"
                    "2. For SIMPLE/CLEAR requests: Execute the tools directly, then call mark_complete(summary='what I did')\n"
                    "3. For COMPLEX requests (5+ deletions, major changes): Propose a plan for confirmation\n\n"
                    "**SIMPLE requests (just do it):**\n"
                    "✓ Change server name\n"
                    "✓ Rename a channel/role\n"
                    "✓ Delete 1-4 specific items\n"
                    "✓ Create a few channels/roles\n"
                    "✓ Modify settings\n"
                    "→ Execute → Call mark_complete() → Done!\n\n"
                    "**COMPLEX requests (propose first):**\n"
                    "✗ Delete 5+ items\n"
                    "✗ Major restructuring\n"
                    "✗ Ambiguous requirements\n"
                    "→ Describe plan → Wait for user confirmation\n\n"
                    "**Example (simple):**\n"
                    "User: 'change server name back'\n"
                    "You: get_server_info() → modify_server_settings(name='Old Name') → mark_complete(summary='Changed server name to Old Name')\n\n"
                    "**DO NOT** just describe what you would do - actually call the tools!"
                )

                # Get or create log channel for question handling
                log_channel = await self.get_or_create_log_channel(message.guild)

                # Create session and process
                tools = create_architect_tools(architect)
                system_message = self.config.get("ai", {}).get("system_message", "")
                model = self.config.get("ai", {}).get("model", "gpt-4")

                session = await self._copilot_client.create_session({
                    "model": model,
                    "streaming": True,
                    "tools": tools,
                    "system_message": {"content": system_message} if system_message else None,
                })

                response_chunks: list[str] = []
                done_event = asyncio.Event()
                tool_activity = {"count": 0, "last_tool": None, "status": "Starting...", "updated": False}

                def on_event(event):
                    event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
                    if event_type == "assistant.message_delta":
                        delta = event.data.delta_content or ""
                        response_chunks.append(delta)
                    elif event_type == "tool.execution.start":
                        tool_activity["count"] += 1
                        if hasattr(event.data, 'name'):
                            tool_activity["last_tool"] = event.data.name
                            # Update status based on tool
                            tool_name = event.data.name
                            if "server_info" in tool_name:
                                tool_activity["status"] = "📊 Checking server structure..."
                            elif "delete" in tool_name:
                                tool_activity["status"] = f"🗑️ Removing items... ({tool_activity['count']} actions)"
                            elif "create" in tool_name:
                                tool_activity["status"] = f"✨ Creating items... ({tool_activity['count']} actions)"
                            elif "permission" in tool_name:
                                tool_activity["status"] = f"🔒 Setting permissions... ({tool_activity['count']} actions)"
                            else:
                                tool_activity["status"] = f"⚙️ Working... ({tool_activity['count']} actions)"
                            tool_activity["updated"] = True
                    elif event_type == "session.idle":
                        done_event.set()

                session.on(on_event)

                # Background task to handle questions from the AI
                async def handle_questions():
                    while not done_event.is_set():
                        if architect.has_pending_question():
                            question_data = architect.get_pending_question()
                            if question_data:
                                self.logger.info(f"AI asked a question: {question_data['question']}")
                                
                                q_embed = discord.Embed(
                                    title="🤔 Envoy needs your input",
                                    description=question_data["question"],
                                    color=discord.Color.gold(),
                                )
                                if question_data.get("context"):
                                    q_embed.add_field(
                                        name="Context",
                                        value=question_data["context"],
                                        inline=False,
                                    )
                                if question_data.get("options"):
                                    q_embed.add_field(
                                        name="Suggested answers",
                                        value="\n".join(f"• {opt}" for opt in question_data["options"]),
                                        inline=False,
                                    )
                                
                                q_view = QuestionView(
                                    question=question_data["question"],
                                    context=question_data.get("context"),
                                    options=question_data.get("options"),
                                    author_id=message.author.id,
                                    timeout=300.0,
                                )
                                
                                if log_channel:
                                    await log_channel.send(embed=q_embed, view=q_view)
                                
                                await q_view.answered.wait()
                                
                                if q_view.answer:
                                    self.logger.info(f"User answered: {q_view.answer}")
                                    architect.set_user_answer(q_view.answer)
                                else:
                                    self.logger.warning("Question timed out")
                                    architect.set_user_answer("(No response - proceed with best judgment)")
                        
                        await asyncio.sleep(0.5)

                # Start question handler
                question_task = asyncio.create_task(handle_questions())

                # Send prompt to Copilot session
                self.logger.debug(f"Sending continuation prompt to Copilot: {enhanced_prompt[:200]}...")
                await session.send({"prompt": enhanced_prompt})
                self.logger.debug("Continuation prompt sent, waiting for response...")

                try:
                    await asyncio.wait_for(done_event.wait(), timeout=120.0)
                except asyncio.TimeoutError:
                    question_task.cancel()
                    await message.reply("⏰ Request timed out.", mention_author=False)
                    await session.destroy()
                    return

                # Cancel background tasks
                question_task.cancel()
                try:
                    await question_task
                except asyncio.CancelledError:
                    pass

                full_response = "".join(response_chunks)

                self.logger.debug(f"Continuation response received. Length: {len(full_response)}, First 200 chars: {full_response[:200]}")

                if not full_response:
                    await message.reply(
                        "❌ No response generated.",
                        mention_author=False,
                    )
                    await session.destroy()
                    return

                # Truncate if needed
                if len(full_response) > 4000:
                    full_response = full_response[:4000] + "\n\n*(truncated)*"

                # Get execution log to check what happened
                exec_log = architect.get_execution_log()
                tool_count = len(exec_log) if exec_log else 0
                
                marked_complete = any("Task completed:" in msg for msg, _ in (exec_log or []))
                
                # Detect if this is a plan proposal that needs confirmation
                response_lower = full_response.lower()
                is_plan_proposal = any([
                    "what i'll do" in response_lower,
                    "what i will do" in response_lower,
                    "here's my plan" in response_lower,
                    "here is my plan" in response_lower,
                    "proposed changes" in response_lower,
                    "i'll make the following" in response_lower,
                    "the following changes" in response_lower and "will" in response_lower,
                ]) and not marked_complete  # If mark_complete was called, it's not a proposal
                
                self.logger.debug(f"Continuation complete. Tool count: {tool_count}, Marked complete: {marked_complete}, Is plan proposal: {is_plan_proposal}")
                
                if is_plan_proposal:
                    embed = discord.Embed(
                        title="📋 Proposed Changes",
                        description=full_response,
                        color=discord.Color.gold(),
                    )
                    embed.set_footer(text="Click Execute to apply these changes, or Cancel to skip")
                    
                    # Create view with confirmation buttons
                    view = ContinuationConfirmView(
                        bot=self,
                        message=message,
                        guild_id=guild_id,
                        proposed_plan=full_response,
                    )
                    reply_msg = await message.reply(embed=embed, view=view, mention_author=False)
                else:
                    # Show execution stats in the embed
                    if tool_count > 0:
                        embed = discord.Embed(
                            title="✅ Done",
                            description=full_response,
                            color=discord.Color.green(),
                        )
                        embed.add_field(
                            name="📊 Actions",
                            value=f"{tool_count} tool calls executed",
                            inline=True,
                        )
                    else:
                        # No tools called - might be a problem
                        embed = discord.Embed(
                            title="⚠️ Response",
                            description=full_response + "\n\n*No actions were taken. If you expected changes, try being more specific.*",
                            color=discord.Color.orange(),
                        )
                    embed.set_footer(text="Reply to this message to continue")
                    reply_msg = await message.reply(embed=embed, mention_author=False)

                # Track this summary message for future continuations
                self._summary_messages[reply_msg.id] = guild_id
                self.logger.debug(f"Registered continuation message ID {reply_msg.id} for guild {guild_id}")

                # Update context with meaningful change history
                if guild_id not in self._session_contexts:
                    self._session_contexts[guild_id] = {"actions": [], "changes": [], "last_response": ""}
                
                # Store the actual change summary for context
                import time
                change_entry = {
                    "request": message.content,
                    "summary": full_response,
                    "timestamp": time.time(),
                    "tool_count": tool_count
                }
                self._session_contexts[guild_id]["changes"].append(change_entry)
                
                # Keep only last 10 changes to avoid memory bloat
                if len(self._session_contexts[guild_id]["changes"]) > 10:
                    self._session_contexts[guild_id]["changes"] = self._session_contexts[guild_id]["changes"][-10:]
                
                # Store execution log for debugging
                if exec_log:
                    formatted_actions = [f"{msg} {'(failed)' if not success else ''}".strip() for msg, success in exec_log[-20:]]
                    self._session_contexts[guild_id]["actions"].extend(formatted_actions)
                
                # Store the AI's response
                self._session_contexts[guild_id]["last_response"] = full_response

                await session.destroy()

            except Exception as e:
                self.logger.exception(f"Error processing continuation: {e}")
                await message.reply(
                    f"❌ An error occurred: {str(e)}",
                    mention_author=False,
                )

    async def get_or_create_log_channel(
        self,
        guild: discord.Guild,
    ) -> Optional[discord.TextChannel]:
        """
        Get or create the Envoy summary channel for execution summaries.

        This channel is positioned at the top of the server and is only
        visible to the server owner and the bot.

        Args:
            guild: The Discord guild.

        Returns:
            The summary channel, or None if creation failed.
        """
        log_channel_name = "envoy-summary"

        # Try to find existing channel
        for channel in guild.text_channels:
            if channel.name == log_channel_name:
                # Ensure it's at position 0
                if channel.position != 0:
                    try:
                        await channel.edit(position=0)
                    except discord.HTTPException:
                        pass
                return channel

        # Create the summary channel
        try:
            # Create with strict permissions - only owner and bot can see
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=False,
                    read_messages=False,
                    send_messages=False,
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=True,
                    embed_links=True,
                    manage_messages=True,
                ),
            }

            # Add owner access
            if guild.owner:
                overwrites[guild.owner] = discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=False,
                    read_message_history=True,
                )

            channel = await guild.create_text_channel(
                name=log_channel_name,
                topic="Envoy bot live progress & summaries. Only visible to server owner.",
                overwrites=overwrites,
                position=0,  # Top of the channel list
                reason="Envoy bot summary channel for live progress updates",
            )

            self.logger.info(f"Created summary channel #{log_channel_name} in {guild.name}")

            # Send welcome message
            embed = discord.Embed(
                title="🏗️ Envoy Summary Channel",
                description=(
                    "This private channel shows live progress during server configuration.\n\n"
                    "**Only you (the server owner) and Envoy can see this channel.**\n\n"
                    "When you run `/architect`, you'll see a live-updating progress embed here "
                    "showing the status of each task as it executes.\n\n"
                    "⚠️ **Do not delete this channel** - it will be recreated automatically."
                ),
                color=discord.Color.blue(),
            )
            await channel.send(embed=embed)

            return channel

        except discord.Forbidden:
            self.logger.error(f"No permission to create summary channel in {guild.name}")
            return None
        except discord.HTTPException as e:
            self.logger.error(f"Failed to create log channel: {e}")
            return None

    def get_architect(self, guild: discord.Guild) -> DiscordArchitect:
        """
        Get or create a DiscordArchitect for a guild.

        Args:
            guild: The Discord guild.

        Returns:
            DiscordArchitect instance for the guild.
        """
        if guild.id not in self._architects:
            rate_config = self.config.get("rate_limits", {})
            rate_limiter = RateLimiter(
                max_calls_per_minute=rate_config.get("max_calls_per_minute", 30),
                min_delay_seconds=rate_config.get("batch_delay", 1.0),
            )

            allow_unsafe = self.config.get("features", {}).get(
                "allow_unsafe_role_ops", False
            )

            self._architects[guild.id] = DiscordArchitect(
                guild=guild,
                rate_limiter=rate_limiter,
                allow_unsafe_role_ops=allow_unsafe,
            )

        return self._architects[guild.id]

    async def process_architect_request(
        self,
        interaction: Interaction,
        prompt: str,
    ) -> None:
        """
        Process an architect request using the Copilot SDK.

        Args:
            interaction: The Discord interaction.
            prompt: The user's natural language prompt.
        """
        if not interaction.guild:
            await interaction.followup.send(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Get the architect for this guild
        architect = self.get_architect(interaction.guild)
        tools = create_architect_tools(architect)

        # Configure session
        ai_config = self.config.get("ai", {})
        model = ai_config.get("model", "gpt-4.1")
        system_message = ai_config.get("system_message", "")
        streaming = ai_config.get("streaming", True)
        require_confirmation = self.config.get("features", {}).get(
            "require_confirmation", True
        )

        try:
            # Create Copilot session with tools
            session = await self._copilot_client.create_session({
                "model": model,
                "streaming": streaming,
                "tools": tools,
                "system_message": {"content": system_message} if system_message else None,
            })

            # Collect the response
            response_chunks: list[str] = []
            plan_generated = False
            done_event = asyncio.Event()
            tool_status = {"current": "Starting analysis...", "updated": False}

            def on_event(event):
                nonlocal plan_generated
                event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)

                if event_type == "assistant.message_delta":
                    delta = event.data.delta_content or ""
                    response_chunks.append(delta)
                elif event_type == "assistant.message":
                    # Check if response indicates a plan
                    content = event.data.content or ""
                    if "plan" in content.lower() or "will" in content.lower():
                        plan_generated = True
                elif event_type == "tool.execution.start":
                    # Update status based on which tool is running
                    if hasattr(event.data, 'name'):
                        tool_name = event.data.name
                        if "server_info" in tool_name:
                            tool_status["current"] = "📊 Checking server structure..."
                        elif "design" in tool_name:
                            tool_status["current"] = "🎨 Loading design templates..."
                        else:
                            tool_status["current"] = "⚙️ Preparing plan..."
                        tool_status["updated"] = True
                elif event_type == "session.idle":
                    done_event.set()

            session.on(on_event)

            # Send initial status message
            status_embed = discord.Embed(
                title="🔍 Analyzing your request...",
                description="Starting analysis...",
                color=discord.Color.blue(),
            )
            status_msg = await interaction.followup.send(embed=status_embed)

            # Background task to update status message
            async def update_status():
                while not done_event.is_set():
                    if tool_status["updated"]:
                        tool_status["updated"] = False
                        try:
                            status_embed.description = tool_status["current"]
                            await status_msg.edit(embed=status_embed)
                        except discord.HTTPException:
                            pass
                    await asyncio.sleep(0.5)

            status_task = asyncio.create_task(update_status())

            # Enhance prompt with context - DO NOT ask AI to list tool names!
            enhanced_prompt = (
                f"User request: {prompt}\n\n"
                f"Server context: {interaction.guild.name} (ID: {interaction.guild.id})\n"
                f"Requesting user: {interaction.user.display_name}\n\n"
                "WORKFLOW:\n"
                "1. Call get_server_info() to see current server structure\n"
                "2. Create a USER-FRIENDLY plan (NO tool names, NO function parameters)\n"
                "3. Wait for confirmation before executing\n\n"
                "PLAN FORMAT (follow exactly):\n"
                "**What I'll Do:**\n"
                "✦ [Simple action description]\n"
                "✦ [Simple action description]\n\n"
                "**Details:**\n"
                "• [Category/role/channel names in plain English]\n\n"
                "⚠️ [Any warnings about destructive actions]\n\n"
                "NEVER show: function names, tool calls, parameters, code, or implementation details."
            )

            # Send the prompt
            await session.send({"prompt": enhanced_prompt})

            # Wait for response with timeout
            try:
                await asyncio.wait_for(done_event.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                status_task.cancel()
                try:
                    await status_msg.delete()
                except discord.HTTPException:
                    pass
                await interaction.followup.send(
                    "⏰ Request timed out. Please try again.",
                    ephemeral=True,
                )
                await session.destroy()
                return

            # Cancel status update task and delete status message
            status_task.cancel()
            try:
                await status_task
            except asyncio.CancelledError:
                pass

            try:
                await status_msg.delete()
            except discord.HTTPException:
                pass

            # Get the full response
            full_response = "".join(response_chunks)

            if not full_response:
                await interaction.followup.send(
                    "❌ No response generated. Please try again.",
                    ephemeral=True,
                )
                await session.destroy()
                return

            # Truncate response if too long for Discord embed (4096 char limit)
            if len(full_response) > 4000:
                full_response = full_response[:4000] + "\n\n*(truncated)*"

            # If confirmation is required, show the plan with buttons
            if require_confirmation:
                view = PlanConfirmationView(
                    timeout=300.0,
                    author_id=interaction.user.id,
                )

                # Create a nice embed for the plan
                plan_embed = discord.Embed(
                    title="📋 Proposed Plan",
                    description=full_response,
                    color=discord.Color.blue(),
                )
                plan_embed.set_footer(text="Click Confirm to execute or Cancel to abort")

                plan_message = await interaction.followup.send(
                    embed=plan_embed,
                    view=view,
                )

                # Wait for user confirmation (with revision loop)
                while True:
                    await view.event.wait()

                    # Handle feedback/revision request
                    if view.feedback:
                        self.logger.info(f"User requested plan revision: {view.feedback}")
                        
                        # Generate revised plan
                        response_chunks.clear()
                        done_event.clear()
                        
                        revision_prompt = (
                            f"The user wants changes to your proposed plan.\n\n"
                            f"**User feedback:**\n{view.feedback}\n\n"
                            f"**Original request:** {prompt}\n\n"
                            "Please revise your plan based on this feedback. "
                            "Use the same format as before:\n\n"
                            "**What I'll Do:**\n"
                            "✦ [Simple action description]\n\n"
                            "**Details:**\n"
                            "• [Category/role/channel names]\n\n"
                            "⚠️ [Any warnings]\n\n"
                            "NEVER show: function names, tool calls, parameters, code."
                        )
                        
                        await session.send({"prompt": revision_prompt})
                        
                        try:
                            await asyncio.wait_for(done_event.wait(), timeout=120.0)
                        except asyncio.TimeoutError:
                            await interaction.followup.send(
                                "⏰ Revision timed out. Please try again.",
                                ephemeral=True,
                            )
                            await session.destroy()
                            return
                        
                        # Get revised response
                        full_response = "".join(response_chunks)
                        if len(full_response) > 4000:
                            full_response = full_response[:4000] + "\n\n*(truncated)*"
                        
                        # Create new view for revised plan
                        view = PlanConfirmationView(
                            timeout=300.0,
                            author_id=interaction.user.id,
                        )
                        
                        revised_embed = discord.Embed(
                            title="📋 Revised Plan",
                            description=full_response,
                            color=discord.Color.blue(),
                        )
                        revised_embed.set_footer(text="Click Confirm to execute or Cancel to abort")
                        
                        plan_message = await interaction.followup.send(
                            embed=revised_embed,
                            view=view,
                        )
                        continue  # Loop back to wait for confirmation
                    
                    # Handle cancel
                    if not view.confirmed:
                        await session.destroy()
                        return
                    
                    # Handle confirm - break out of loop
                    break

                # Get or create summary channel BEFORE execution (in case channels are deleted)
                log_channel = await self.get_or_create_log_channel(interaction.guild)

                # Set up progress tracker for live updates
                if log_channel:
                    architect.progress_tracker.set_channel(log_channel)
                    architect.progress_tracker.reset()
                    # Send initial progress embed
                    await architect.progress_tracker.send_initial()

                # User confirmed - execute the plan
                execution_chunks: list[str] = []
                exec_done = asyncio.Event()

                def on_exec_event(event):
                    event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
                    if event_type == "assistant.message_delta":
                        delta = event.data.delta_content or ""
                        execution_chunks.append(delta)
                    elif event_type == "session.idle":
                        exec_done.set()

                session.on(on_exec_event)

                # Background task to handle questions from the AI
                async def handle_questions():
                    while not exec_done.is_set():
                        # Check if there's a pending question
                        if architect.has_pending_question():
                            question_data = architect.get_pending_question()
                            if question_data:
                                self.logger.info(f"AI asked a question: {question_data['question']}")
                                
                                # Build the question embed
                                q_embed = discord.Embed(
                                    title="🤔 Envoy needs your input",
                                    description=question_data["question"],
                                    color=discord.Color.gold(),
                                )
                                if question_data.get("context"):
                                    q_embed.add_field(
                                        name="Context",
                                        value=question_data["context"],
                                        inline=False,
                                    )
                                if question_data.get("options"):
                                    q_embed.add_field(
                                        name="Suggested answers",
                                        value="\n".join(f"• {opt}" for opt in question_data["options"]),
                                        inline=False,
                                    )
                                
                                # Create the view with the answer button
                                q_view = QuestionView(
                                    question=question_data["question"],
                                    context=question_data.get("context"),
                                    options=question_data.get("options"),
                                    author_id=interaction.user.id,
                                    timeout=300.0,
                                )
                                
                                # Send to log channel
                                if log_channel:
                                    await log_channel.send(embed=q_embed, view=q_view)
                                
                                # Wait for the user's answer
                                await q_view.answered.wait()
                                
                                if q_view.answer:
                                    self.logger.info(f"User answered: {q_view.answer}")
                                    architect.set_user_answer(q_view.answer)
                                else:
                                    self.logger.warning("Question timed out or was not answered")
                                    architect.set_user_answer("(No response - proceed with your best judgment)")
                        
                        await asyncio.sleep(0.5)  # Check every 500ms

                # Start the question handler as a background task
                question_task = asyncio.create_task(handle_questions())

                await session.send({
                    "prompt": (
                        "The user has confirmed the plan. Execute it now using the available tools.\n\n"
                        "IMPORTANT - Progress Tracking:\n"
                        "1. FIRST call set_plan() with a title and list of task names\n"
                        "2. Before each major operation, call update_task() with status='in_progress'\n"
                        "3. After each operation completes, call update_task() with status='completed' or 'failed'\n"
                        "4. This updates a live progress embed visible to the server owner\n\n"
                        "If you need clarification, use ask_user() - a popup will appear for the user to answer.\n\n"
                        "Example workflow:\n"
                        "- set_plan(title='Gaming Server', tasks=['Create roles', 'Create categories', 'Set permissions'])\n"
                        "- update_task(task_id=1, status='in_progress')\n"
                        "- create_role(...)\n"
                        "- update_task(task_id=1, status='completed')\n"
                        "- update_task(task_id=2, status='in_progress')\n"
                        "- etc."
                    )
                })

                try:
                    await asyncio.wait_for(exec_done.wait(), timeout=300.0)
                except asyncio.TimeoutError:
                    timeout_msg = "⏰ Execution timed out."
                    try:
                        await interaction.followup.send(timeout_msg)
                    except discord.HTTPException:
                        if log_channel:
                            await log_channel.send(timeout_msg)
                finally:
                    # Cancel the question handler task
                    question_task.cancel()
                    try:
                        await question_task
                    except asyncio.CancelledError:
                        pass
                    # Clear any pending question state
                    architect.clear_question_state()

                exec_response = "".join(execution_chunks)

                exec_log = architect.get_execution_log()

                actions_file = None
                if exec_log:
                    actions_content = "ENVOY BOT - EXECUTION LOG\n"
                    actions_content += f"Server: {interaction.guild.name}\n"
                    actions_content += f"Requested by: {interaction.user.display_name}\n"
                    actions_content += f"Time: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    actions_content += f"Total Actions: {len(exec_log)}\n"
                    actions_content += "=" * 60 + "\n\n"
                    
                    for idx, (msg, success) in enumerate(exec_log, 1):
                        status = "✓" if success else "✗ (failed)"
                        actions_content += f"{idx}. [{status}] {msg}\n"
                    
                    actions_file = discord.File(
                        fp=io.BytesIO(actions_content.encode('utf-8')),
                        filename=f"envoy_actions_{int(discord.utils.utcnow().timestamp())}.txt"
                    )

                embed = discord.Embed(
                    title="✅ Execution Complete",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow(),
                )

                embed.set_footer(
                    text=f"Requested by {interaction.user.display_name}",
                    icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                )

                if exec_response:
                    summary_text = exec_response
                    field_num = 0
                    while summary_text and field_num < 4:
                        chunk = summary_text[:1020]
                        if len(summary_text) > 1020:
                            last_newline = chunk.rfind('\n')
                            if last_newline > 800:
                                chunk = summary_text[:last_newline]
                        summary_text = summary_text[len(chunk):].lstrip()
                        
                        field_name = "📋 Summary" if field_num == 0 else "📋 Summary (cont.)"
                        embed.add_field(
                            name=field_name,
                            value=chunk or "No details",
                            inline=False,
                        )
                        field_num += 1

                embed.add_field(
                    name="📊 Stats",
                    value=f"Total actions: {len(exec_log) if exec_log else 0}",
                    inline=True,
                )

                embed.set_footer(text="Reply to this message to continue configuring")

                if log_channel:
                    try:
                        if actions_file:
                            summary_msg = await log_channel.send(embed=embed, file=actions_file)
                        else:
                            summary_msg = await log_channel.send(embed=embed)
                        
                        self._summary_messages[summary_msg.id] = interaction.guild.id
                        self.logger.debug(
                            f"Registered initial architect summary message ID {summary_msg.id} for guild {interaction.guild.id}"
                        )
                        
                        import time
                        formatted_actions = [f"{msg} {'(failed)' if not success else ''}".strip() for msg, success in exec_log] if exec_log else []
                        self._session_contexts[interaction.guild.id] = {
                            "actions": formatted_actions[-20:],
                            "changes": [{
                                "request": prompt,
                                "summary": exec_response or "Execution completed",
                                "timestamp": time.time(),
                                "tool_count": len(exec_log) if exec_log else 0
                            }],
                            "last_response": exec_response or ""
                        }
                    except discord.HTTPException as e:
                        self.logger.error(f"Failed to send to log channel: {e}")
                        try:
                            await interaction.followup.send(embed=embed)
                        except discord.HTTPException:
                            pass

            else:
                # No confirmation required - just show the response
                await interaction.followup.send(full_response)

            await session.destroy()

        except Exception as e:
            self.logger.exception(f"Error processing architect request: {e}")
            error_msg = f"❌ An error occurred: {str(e)}"
            try:
                await interaction.followup.send(error_msg, ephemeral=True)
            except discord.HTTPException:
                # Try to send to log channel as fallback
                try:
                    log_channel = await self.get_or_create_log_channel(interaction.guild)
                    if log_channel:
                        embed = discord.Embed(
                            title="❌ Execution Error",
                            description=f"An error occurred while processing a request from {interaction.user.mention}:\n\n```{str(e)[:1800]}```",
                            color=discord.Color.red(),
                            timestamp=discord.utils.utcnow(),
                        )
                        await log_channel.send(embed=embed)
                except Exception:
                    pass  # Last resort - just log it


# ============================================================================
# Slash Commands
# ============================================================================


def setup_commands(bot: EnvoyBot) -> None:
    """
    Set up slash commands for the bot.

    Args:
        bot: The EnvoyBot instance.
    """

    @bot.tree.command(
        name="architect",
        description="Configure your Discord server using natural language",
    )
    @app_commands.describe(
        prompt="Describe what you want to do with your server"
    )
    async def architect_command(
        interaction: Interaction,
        prompt: str,
    ) -> None:
        """
        Main command for server configuration.
        
        Only the server owner or users on the allowlist can use this command.

        Args:
            interaction: The Discord interaction.
            prompt: Natural language description of desired changes.
        """
        # Check if user is owner or on allowlist
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return
            
        if not bot._guild_configs.is_allowed(
            interaction.guild.id,
            interaction.user.id,
            interaction.guild.owner_id,
        ):
            await interaction.response.send_message(
                "❌ Only the server owner or users on the allowlist can use this command.\n"
                "Ask the server owner to run `/architect-allow` to grant you access.",
                ephemeral=True,
            )
            return

        # Check user quota
        allowed, error_msg = bot._user_quotas.check_architect_quota(interaction.user.id)
        if not allowed:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)

        # Record usage AFTER defer but BEFORE processing (counts even if errors occur)
        bot._user_quotas.use_architect(interaction.user.id)

        # Check for prohibited content (hate/extremism/NSFW). If present, refuse and log.
        matched = bot.contains_prohibited_content(prompt)
        if matched:
            bot.logger.warning(
                f"Prohibited architect request blocked from {interaction.user} in {interaction.guild}: {prompt}"
            )
            await interaction.followup.send(
                "❌ I can't assist with creating or organizing hateful, extremist, or sexually explicit/NSFW servers or content. "
                "If you need help with moderation, safety, or non-NSFW community setups, I can help with that.",
                ephemeral=True,
            )
            return

        bot.logger.info(
            f"Architect request from {interaction.user} in {interaction.guild}: {prompt}"
        )

        await bot.process_architect_request(interaction, prompt)

    @bot.tree.command(
        name="envoy-info",
        description="Display information about the Envoy bot",
    )
    async def info_command(interaction: Interaction) -> None:
        """Display bot information."""
        embed = discord.Embed(
            title="🤖 Envoy - Discord Server Architect",
            description=(
                "Envoy is an AI-powered bot that helps you configure and manage "
                "your Discord server using natural language commands."
            ),
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="📝 How to Use",
            value=(
                "Use `/architect` followed by a description of what you want to do.\n\n"
                "**Examples:**\n"
                "• `/architect Create a professional coding server with Dev, QA, and Ops roles`\n"
                "• `/architect Set up private channels for team leads`\n"
                "• `/architect Create a gaming category with voice and text channels`"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔧 Capabilities",
            value=(
                "• Create/delete channels and categories\n"
                "• Create/delete roles with custom permissions\n"
                "• Set channel-specific permissions\n"
                "• Modify server settings"
            ),
            inline=True,
        )

        embed.add_field(
            name="⚠️ Requirements",
            value=(
                "• Server owner or on allowlist to use `/architect`\n"
                "• Use `/architect-allowlist` to see who has access\n"
                "• Bot needs Manage Server, Channels, and Roles permissions"
            ),
            inline=True,
        )

        embed.set_footer(text="Powered by GitHub Copilot SDK")

        await interaction.response.send_message(embed=embed)

    @bot.tree.command(
        name="envoy-quota",
        description="Check your daily usage quota for Envoy",
    )
    async def quota_command(interaction: Interaction) -> None:
        """Display the user's current usage quota."""
        stats = bot._user_quotas.get_usage_stats(interaction.user.id)
        
        # Build progress bars
        def progress_bar(used: int, limit: int) -> str:
            filled = min(used, limit)
            remaining = limit - filled
            bar = "█" * filled + "░" * remaining
            return f"`{bar}` {used}/{limit}"
        
        embed = discord.Embed(
            title="📊 Your Envoy Usage Quota",
            color=discord.Color.blue(),
        )
        
        # Architect quota
        architect_status = "✅" if stats["architect_remaining"] > 0 else "❌"
        embed.add_field(
            name=f"{architect_status} /architect Commands",
            value=(
                f"{progress_bar(stats['architect_used'], stats['architect_limit'])}\n"
                f"**Remaining:** {stats['architect_remaining']}"
            ),
            inline=False,
        )
        
        # Continuation quota
        cont_status = "✅" if stats["continuation_remaining"] > 0 else "❌"
        embed.add_field(
            name=f"{cont_status} Reply Continuations",
            value=(
                f"{progress_bar(stats['continuation_used'], stats['continuation_limit'])}\n"
                f"**Remaining:** {stats['continuation_remaining']}"
            ),
            inline=False,
        )
        
        # Reset time
        reset_ts = stats["reset_timestamp"]
        embed.add_field(
            name="🔄 Quota Resets",
            value=f"<t:{reset_ts}:R> (<t:{reset_ts}:F>)",
            inline=False,
        )
        
        embed.set_footer(text="Quotas reset daily at midnight UTC")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="envoy-preview",
        description="Preview the current server structure",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def preview_command(interaction: Interaction) -> None:
        """Preview the current server structure."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        architect = bot.get_architect(interaction.guild)
        result = await architect.get_server_info()

        if not result.success:
            await interaction.followup.send(f"❌ {result.message}")
            return

        data = result.data

        # Build embed
        embed = discord.Embed(
            title=f"📊 Server Structure: {data['name']}",
            color=discord.Color.green(),
        )

        # Categories and channels info
        cat_info = []
        for cat in data.get("categories", []):
            cat_info.append(f"📁 **{cat['name']}** ({len(cat.get('children', []))} channels)")

        if cat_info:
            embed.add_field(
                name="Categories",
                value="\n".join(cat_info[:10]) or "None",
                inline=False,
            )

        # Channel counts
        embed.add_field(
            name="Channels",
            value=(
                f"📝 Text: {len(data.get('text_channels', []))}\n"
                f"🔊 Voice: {len(data.get('voice_channels', []))}"
            ),
            inline=True,
        )

        # Role count
        embed.add_field(
            name="Roles",
            value=f"🎭 {len(data.get('roles', []))} roles",
            inline=True,
        )

        # Member count
        embed.add_field(
            name="Members",
            value=f"👥 {data.get('member_count', 'N/A')}",
            inline=True,
        )

        await interaction.followup.send(embed=embed)

    @bot.tree.command(
        name="get-webhook",
        description="Get the webhook URL for a channel (for editing bot-posted embeds)",
    )
    @app_commands.describe(
        channel="The channel to get/create a webhook for"
    )
    @app_commands.checks.has_permissions(manage_webhooks=True)
    async def get_webhook_command(
        interaction: Interaction,
        channel: discord.TextChannel,
    ) -> None:
        """Get or create a webhook for a channel."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Find existing Envoy webhook or create one
            webhooks = await channel.webhooks()
            webhook = None
            for wh in webhooks:
                if wh.name == "Envoy":
                    webhook = wh
                    break

            if not webhook:
                webhook = await channel.create_webhook(
                    name="Envoy",
                    reason="Created by Envoy bot for embed posting/editing",
                )

            # Send webhook URL privately
            embed = discord.Embed(
                title="🔗 Webhook URL",
                description=(
                    f"**Channel:** #{channel.name}\n\n"
                    f"**Webhook URL:**\n||{webhook.url}||\n\n"
                    "⚠️ **Keep this URL secret!** Anyone with this URL can post messages to this channel."
                ),
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="💡 How to Edit Embeds",
                value=(
                    "Use tools like [Discohook](https://discohook.org/) or "
                    "[Embed Visualizer](https://leovoel.github.io/embed-visualizer/) "
                    "to create/edit embeds using this webhook URL."
                ),
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to manage webhooks in that channel.",
                ephemeral=True,
            )
        except Exception as e:
            bot.logger.error(f"Error getting webhook: {e}")
            await interaction.followup.send(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True,
            )

    @get_webhook_command.error
    async def get_webhook_error(
        interaction: Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Handle get-webhook command errors."""
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need Manage Webhooks permission to use this command.",
                ephemeral=True,
            )
        else:
            bot.logger.error(f"Get webhook command error: {error}")

    # ========================================================================
    # Server Export/Import Commands
    # ========================================================================

    @bot.tree.command(
        name="export-server",
        description="Export your server structure to a .envoy file (server owner only)",
    )
    async def export_server_command(
        interaction: Interaction,
    ) -> None:
        """Export the server structure to a .envoy file."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Only server owner can export
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can export the server structure.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            architect = bot.get_architect(interaction.guild)
            result = await architect.export_server()

            if not result.success:
                await interaction.followup.send(
                    f"❌ {result.message}",
                    ephemeral=True,
                )
                return

            # Convert to JSON
            import json
            import io

            export_json = json.dumps(result.data, indent=2, ensure_ascii=False)
            
            # Create file
            filename = f"{interaction.guild.id}.envoy"
            file = discord.File(
                io.BytesIO(export_json.encode('utf-8')),
                filename=filename,
            )

            embed = discord.Embed(
                title="📦 Server Export Complete",
                description=(
                    f"**Exported:**\n"
                    f"• {len(result.data.get('roles', []))} roles\n"
                    f"• {len(result.data.get('categories', []))} categories\n"
                    f"• {len(result.data.get('channels', []))} channels\n"
                    f"• {len(result.data.get('webhooks', []))} webhooks\n\n"
                    f"**File:** `{filename}`\n\n"
                    "Use `/import-server` with this file to recreate the structure on another server."
                ),
                color=discord.Color.green(),
            )
            embed.set_footer(text="Note: Messages, members, and invites are not exported.")

            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            bot.logger.info(f"Server export completed for {interaction.guild.name} by {interaction.user}")

        except Exception as e:
            bot.logger.exception(f"Error exporting server: {e}")
            await interaction.followup.send(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True,
            )

    @bot.tree.command(
        name="import-server",
        description="Import a server structure from a .envoy file (server owner only)",
    )
    @app_commands.describe(
        file="The .envoy file to import",
        clear_existing="Delete existing channels/roles before importing (default: False)",
    )
    async def import_server_command(
        interaction: Interaction,
        file: discord.Attachment,
        clear_existing: bool = False,
    ) -> None:
        """Import a server structure from a .envoy file."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Only server owner can import
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can import server structures.",
                ephemeral=True,
            )
            return

        # Validate file
        if not file.filename.endswith('.envoy'):
            await interaction.response.send_message(
                "❌ Please upload a valid `.envoy` file.",
                ephemeral=True,
            )
            return

        if file.size > 10 * 1024 * 1024:  # 10MB limit
            await interaction.response.send_message(
                "❌ File is too large. Maximum size is 10MB.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=False)

        try:
            import json

            # Download and parse the file
            file_content = await file.read()
            data = json.loads(file_content.decode('utf-8'))

            # Validate the data structure
            if not isinstance(data, dict) or 'version' not in data:
                await interaction.followup.send(
                    "❌ Invalid .envoy file format.",
                    ephemeral=True,
                )
                return

            # Show confirmation embed with what will be imported
            preview_embed = discord.Embed(
                title="📥 Import Preview",
                description=(
                    f"**From file:** `{file.filename}`\n"
                    f"**Original server:** {data.get('server', {}).get('name', 'Unknown')}\n"
                    f"**Exported:** {data.get('exported_at', 'Unknown')}\n\n"
                    f"**Will import:**\n"
                    f"• {len(data.get('roles', []))} roles\n"
                    f"• {len(data.get('categories', []))} categories\n"
                    f"• {len(data.get('channels', []))} channels\n"
                    f"• {len(data.get('webhooks', []))} webhooks\n\n"
                ),
                color=discord.Color.gold(),
            )

            if clear_existing:
                preview_embed.add_field(
                    name="⚠️ Warning",
                    value="**Clear existing content is enabled!**\nThis will delete most existing channels and roles before importing.",
                    inline=False,
                )

            preview_embed.set_footer(text="Starting import...")

            await interaction.followup.send(embed=preview_embed)

            # Perform the import
            architect = bot.get_architect(interaction.guild)
            result = await architect.import_server(data, clear_existing=clear_existing)

            if result.success:
                stats = result.data or {}
                result_embed = discord.Embed(
                    title="✅ Import Complete",
                    description=(
                        f"**Created:**\n"
                        f"• {stats.get('roles_created', 0)} roles\n"
                        f"• {stats.get('categories_created', 0)} categories\n"
                        f"• {stats.get('channels_created', 0)} channels\n"
                        f"• {stats.get('webhooks_created', 0)} webhooks"
                    ),
                    color=discord.Color.green(),
                )

                if stats.get('errors'):
                    error_text = "\n".join(f"• {e[:100]}" for e in stats['errors'][:10])
                    if len(stats['errors']) > 10:
                        error_text += f"\n... and {len(stats['errors']) - 10} more"
                    result_embed.add_field(
                        name=f"⚠️ Errors ({len(stats['errors'])})",
                        value=error_text[:1024],
                        inline=False,
                    )

                await interaction.followup.send(embed=result_embed)
            else:
                await interaction.followup.send(f"❌ {result.message}")

            bot.logger.info(f"Server import completed for {interaction.guild.name} by {interaction.user}")

        except json.JSONDecodeError:
            await interaction.followup.send(
                "❌ Invalid JSON in .envoy file.",
                ephemeral=True,
            )
        except Exception as e:
            bot.logger.exception(f"Error importing server: {e}")
            await interaction.followup.send(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True,
            )

    # ========================================================================
    # Allowlist Management Commands
    # ========================================================================

    @bot.tree.command(
        name="architect-allow",
        description="Allow a user to use the /architect command (server owner only)",
    )
    @app_commands.describe(
        user="The user to allow"
    )
    async def architect_allow_command(
        interaction: Interaction,
        user: discord.Member,
    ) -> None:
        """Add a user to the architect allowlist."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Only server owner can manage allowlist
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can manage the architect allowlist.",
                ephemeral=True,
            )
            return

        if user.bot:
            await interaction.response.send_message(
                "❌ Cannot add bots to the allowlist.",
                ephemeral=True,
            )
            return

        if user.id == interaction.guild.owner_id:
            await interaction.response.send_message(
                "ℹ️ The server owner already has access by default.",
                ephemeral=True,
            )
            return

        if bot._guild_configs.add_to_allowlist(interaction.guild.id, user.id):
            await interaction.response.send_message(
                f"✅ {user.mention} can now use `/architect`.",
                ephemeral=True,
            )
            bot.logger.info(
                f"{interaction.user} added {user} to architect allowlist in {interaction.guild}"
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ {user.mention} is already on the allowlist.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="architect-remove",
        description="Remove a user's access to the /architect command (server owner only)",
    )
    @app_commands.describe(
        user="The user to remove"
    )
    async def architect_remove_command(
        interaction: Interaction,
        user: discord.Member,
    ) -> None:
        """Remove a user from the architect allowlist."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Only server owner can manage allowlist
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can manage the architect allowlist.",
                ephemeral=True,
            )
            return

        if bot._guild_configs.remove_from_allowlist(interaction.guild.id, user.id):
            await interaction.response.send_message(
                f"✅ {user.mention} can no longer use `/architect`.",
                ephemeral=True,
            )
            bot.logger.info(
                f"{interaction.user} removed {user} from architect allowlist in {interaction.guild}"
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ {user.mention} was not on the allowlist.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="architect-allowlist",
        description="View who can use the /architect command",
    )
    async def architect_allowlist_command(
        interaction: Interaction,
    ) -> None:
        """Show the current architect allowlist."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        allowlist = bot._guild_configs.get_allowlist(interaction.guild.id)

        embed = discord.Embed(
            title="🔐 Architect Allowlist",
            color=discord.Color.blue(),
        )

        # Always include owner
        owner = interaction.guild.owner
        owner_text = f"👑 {owner.mention} (Server Owner)" if owner else "👑 Server Owner"
        
        if allowlist:
            user_mentions = []
            for user_id in allowlist:
                member = interaction.guild.get_member(user_id)
                if member:
                    user_mentions.append(f"• {member.mention}")
                else:
                    user_mentions.append(f"• Unknown User ({user_id})")
            
            embed.description = (
                f"**Always Allowed:**\n{owner_text}\n\n"
                f"**Allowlist ({len(allowlist)}):**\n" + "\n".join(user_mentions)
            )
        else:
            embed.description = (
                f"**Always Allowed:**\n{owner_text}\n\n"
                "**Allowlist:**\nNo additional users. Use `/architect-allow` to add users."
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Error handlers
    @architect_command.error
    async def architect_error(
        interaction: Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Handle architect command errors."""
        bot.logger.error(f"Architect command error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"❌ An error occurred: {str(error)}",
                ephemeral=True,
            )

    @preview_command.error
    async def preview_error(
        interaction: Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Handle preview command errors."""
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need Manage Server permission to use this command.",
                ephemeral=True,
            )
        else:
            bot.logger.error(f"Preview command error: {error}")


# ============================================================================
# Main Entry Point
# ============================================================================


async def main() -> None:
    """Main entry point for the Envoy bot."""
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing config.yml: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    # Setup logging
    logger = setup_logging(config)
    logger.info("Starting Envoy bot...")

    # Create and run bot
    bot = EnvoyBot(config)
    setup_commands(bot)

    token = config["discord"]["token"]

    try:
        async with bot:
            await bot.start(token)
    except discord.LoginFailure:
        logger.error("Invalid Discord token. Please check your config.yml")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
