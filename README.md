# 🤖 Envoy - Agentic Discord Server Architect

Envoy is an AI-powered Discord bot that autonomously configures and manages Discord servers based on natural language commands. Powered by the **GitHub Copilot SDK**, Envoy interprets your requests, generates execution plans, and performs Discord API operations through intelligent function calling.

# Our official bot on discord is Envoy#5176
- Never use any other bot claiming to be the official Envoy as it could be malicious and nuke your server.

# Security warning:
- This bot has powerful permissions and can modify your server structure. Only the server owner may execute the architect command, You need to be authorized to use the commands by the owner of the Server.
- This bot can nuke your server if given malicious instructions. Use with caution, We are not responsible for any damage caused by misuse of this bot or vulnerabilities in the AI model.

## ✨ Features

- **Natural Language Interface** - Describe what you want in plain English
- **Agentic Execution** - Uses AI function calling to interact with the Discord API
- **Draft Plans with Confirmation** - Review proposed changes before execution
- **Permission Guardrails** - Validates bot permissions before attempting operations
- **Rate Limiting** - Built-in protection against Discord API rate limits
- **Comprehensive Logging** - Detailed server-side logs for debugging and auditing

## 📋 Prerequisites

Before installing Envoy, ensure you have:

1. **Python 3.11+** installed
2. **GitHub Copilot CLI** installed and authenticated
   - [Installation guide](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli)
   - Verify with: `copilot --version`
3. **A GitHub Copilot subscription** (Free tier works with limited 50 messages quota)
4. **A Discord Bot Token**

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/HoppouAI/Envoy-Bot.git
cd Envoy-Bot
```

### 2. Create Virtual Environment (UV)

```bash
uv venv --python 3.11

```bash
or without UV:
python -m venv .venv
```
Make sure you have atleast python 3.11 installed.

# Windows
.venv\Scripts\activate

# Unix/macOS
source .venv/bin/activate
```

### 3. Install Dependencies with UV

```bash
uv pip install -r requirements.txt
```
or without UV:
```bash
pip install -r requirements.txt
```

### 4. Configure the Bot

Copy the sample configuration and add your Discord token:


Edit `config.yml` and replace `YOUR_DISCORD_BOT_TOKEN_HERE` with your actual token.

### 5. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and name it "Envoy"
3. Go to the **Bot** section and click "Add Bot"
4. Copy the **Token** and paste it in `config.yml`
5. Enable these **Privileged Gateway Intents**:
   - Server Members Intent
   - Message Content Intent
6. Go to **OAuth2 > URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions:
     - Manage Server
     - Manage Roles
     - Manage Channels
     - Send Messages
     - Embed Links
     - Read Message History
7. Copy the generated URL and invite the bot to your server

### 6. Run the Bot

```bash
python main.py
```
or
```bash
uv run main.py
```

You should see:
```
[INFO] Starting Envoy bot...
[INFO] Copilot SDK client initialized
[INFO] Synced 3 slash commands
[INFO] Logged in as username#1234 (ID: 123456789)
[INFO] Connected to 1 (or however many its in) guilds
```

## 💬 Usage

### Basic Commands

| Command | Description |
|---------|-------------|
| `/architect <prompt>` | Configure your server with natural language |
| `/envoy-info` | Display bot information and examples |
| `/envoy-preview` | Preview current server structure |

### Example Prompts

```
/architect Create a professional coding server with Dev, QA, and Ops roles, 
           each with appropriate permissions and dedicated channels
```

```
/architect Set up a gaming category with voice channels for different games 
           and a text channel for LFG posts
```

```
/architect Create private team-lead channels that only managers can see
```

```
/architect Add a welcome channel with slowmode and set the server 
           verification level to medium
```

### Workflow

1. **Send a Request** - Use `/architect` with your description
2. **Review the Plan** - Envoy generates a detailed execution plan
3. **Confirm or Cancel** - Click ✅ to execute or ❌ to cancel
4. **Execution** - Envoy performs the operations and reports results

## 🔧 Configuration

### config.yml Reference

```yaml
# Discord Configuration
discord:
  token: "YOUR_TOKEN"          # Required: Bot token
  prefix: "!"                  # Command prefix (slash commands are primary)
  command_cooldown: 5          # Cooldown between commands (seconds)

# AI Configuration
ai:
  model: "gpt-4.1"             # Copilot model to use
  temperature: 0.7             # Response creativity (0.0-1.0)
  streaming: true              # Enable streaming responses
  system_message: |            # Custom instructions for the AI
    You are Envoy, an expert Discord server architect...

# Rate Limiting
rate_limits:
  max_calls_per_minute: 30     # Max API calls per minute
  batch_delay: 1.0             # Delay between batch operations
  max_concurrent_ops: 5        # Max concurrent operations

# Logging
logging:
  level: "INFO"                # DEBUG, INFO, WARNING, ERROR, CRITICAL
  file: "logs/envoy.log"       # Log file path
  max_size_mb: 10              # Max log file size before rotation
  backup_count: 5              # Number of backup logs to keep

# Features
features:
  require_confirmation: true   # Require user confirmation before execution
  verbose_execution: false     # Show detailed logs in Discord
  allow_unsafe_role_ops: false # Allow operations on higher roles (dangerous)
```

### Available AI Models

The following models work with the Copilot SDK:
- `gpt-4.1` (recommended)
- `gpt-5`
- `claude-sonnet-4.5`

Check available models with the Copilot CLI:
```bash
copilot list-models
```

## 🛠️ Available Tools

Envoy exposes these tools to the AI for function calling:

| Tool | Description |
|------|-------------|
| `create_channel` | Create text, voice, or category channels |
| `create_role` | Create roles with custom permissions and colors |
| `set_permissions` | Set channel-specific permission overrides |
| `create_category` | Create a category with multiple child channels |
| `modify_server_settings` | Change server name, verification level, etc. |
| `delete_channel` | Remove a channel from the server |
| `delete_role` | Remove a role from the server |
| `get_server_info` | Fetch current server structure |

## 🔐 Security Considerations

1. **Permission Hierarchy** - The bot cannot modify roles positioned above its own highest role
2. **Admin Required** - Only server administrators can use `/architect`
3. **Confirmation Flow** - All changes require explicit user approval (configurable)

### Recommended .gitignore

```gitignore
# Configuration with secrets
config.yml

# Logs
logs/

# Virtual environment
venv/

# Python cache
__pycache__/
*.pyc

# IDE
.vscode/
.idea/
```

## 📁 Project Structure

```
Envoy-Bot/
├── main.py           # Entry point, Discord events, command handling
├── architect.py      # DiscordArchitect class and tool definitions
├── config.yml        # Configuration (not committed with secrets)
├── requirements.txt  # Python dependencies
├── README.md         # This file
└── logs/             # Log files (auto-created)
    └── envoy.log
```

## 🐛 Troubleshooting

### Bot doesn't respond to commands

1. Ensure the bot has the required permissions
2. Check that slash commands are synced (happens on startup)
3. Verify the bot is online in your server

### "Copilot CLI not found" error

1. Install the Copilot CLI: [Installation guide](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli)
2. Ensure `copilot` is in your PATH
3. Authenticate with: `copilot auth login`

### Rate limit errors

1. Reduce `max_calls_per_minute` in config
2. Increase `batch_delay` for large operations
3. The bot has built-in rate limiting, but complex requests may still hit limits

### Permission errors

1. Ensure the bot role is high enough in the role hierarchy
2. Check that the bot has Administrator or specific required permissions
3. The bot cannot modify roles above its own position

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Test your changes
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- [discord.py](https://github.com/Rapptz/discord.py) - Discord API wrapper
- [GitHub Copilot SDK](https://github.com/github/copilot-sdk) - AI/LLM engine
---

**Note:** This bot is powered by the GitHub Copilot SDK, which is currently in Technical Preview. Features and APIs may change.
