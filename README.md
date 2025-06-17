[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/motebus-ultra-mcp-ss-badge.png)](https://mseep.ai/app/motebus-ultra-mcp-ss)


<p align="center"> <img src="./img/mcp-ss.png" alt="drawing" width="400"/></p>

ultra/mcp-ss is a FastAPI-based MCP server that integrates with smartscreen.tv, a web display service, allowing you to programmatically manipulate the screen (e.g., display media, send notifications, control playback) via simple HTTP/MCP commands.

<table align="center">
  <tr >
    <td valign="top">

## Table of Contents
- [What is SmartScreen?](#what-is-smartscreen)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Docker](#docker)
- [API Endpoints](#api-endpoints)
  - [Health & Search](#health--search)
  - [SmartScreen Commands (HTTP)](#smartscreen-commands-http)
- [MCP Tool Integration](#mcp-tool-integration)
- [Using MCP Proxy for Clients Without SSE Support](#using-mcp-proxy-for-clients-without-sse-support-claude-desktop)
- [Setting up MCP-SS in Langflow](#setting-up-mcp-ss-in-langflow)
- [Contributing](#contributing)

    </td>
    <td valign="middle" align="center">
<p align="center">
  <img src="./img/mcp-white.png" width="100" alt="mcp logo">
</p>
<p align="center">
  <img src="./img/arrow.webp" width="50" alt="mcp logo">
</p>
<p align="center">
  <img src="./img/ss-logo.png" width="100" alt="mcp logo">
</p>

  </td>
  </tr>
</table>


## What is SmartScreen?

SmartScreen is a web-based screening service.  
Content across multiple displays and locations can be controlled remotely. Simply add the MCP tool to your AI app.

SmartScreen setup:
1. Access SmartScreen through URL: smartscreen.tv  
![Smartscreen](./img/smartscreen-main.png "Smartscreen")
   * On Linux, SmartScreen can be installed via snapcraft.
2. Click the menu button on the top-left corner to reach 
**Settings**. Here you can name your device, add tags, and set up OnStart and other scheduled events.  
![Settings](./img/settings.png "Settings")
   * Don’t forget to click “Save” after making any changes.
3. Click **SmartScreen** to return to the Home Page.

# ultra/mcp-ss

## Prerequisites
- Python 3.12+
- Docker (optional, for containerized deployment)
- YOUTUBE_API_KEY set up from Google Console for "YouTube Data API v3"
- SS_SERVICE_TOKEN environment variable

## Configuration
Create a `.env` file or export environment variables:
- YOUTUBE_API_KEY – your Google YouTube Data API v3 key  
- SS_SERVICE_TOKEN – SmartScreen service token

Example `.env`:
```dotenv
YOUTUBE_API_KEY=AIzaSy...
SS_SERVICE_TOKEN=xxxxx
```
or export them:
```bash
export YOUTUBE_API_KEY=AIzaSy...
export SS_SERVICE_TOKEN=xxxxx
```

## Running Locally
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Docker
```bash
docker build -t ultra-mcp-ss .
docker run -d --name ultra-mcp-ss -p 127.0.0.1:8000:8000 ultra-mcp-ss
```
## API Endpoints
Base URL: `http://127.0.0.1:8000`

### Health & Search

- `HEAD /mcp` – health check for MCP  
- `GET /search-youtube?query=...` – returns the most relevant YouTube video URL

### SmartScreen Commands (HTTP)

| Endpoint        | Description                                          |
| --------------- | ---------------------------------------------------- |
| POST /drop      | Drop media URL onto a screen frame                  |
| POST /notify    | Send a notification banner                          |
| POST /toast     | Show a toast popup message                          |
| POST /marquee   | Display scrolling marquee text                      |
| POST /text      | Render static text overlay                          |
| POST /app       | Launch a web app in a frame                         |
| POST /touch     | Send playback/control commands                      |
| POST /status    | Query or set system status                          |
| POST /dj        | Execute DJ tasks: scheduling, kiosk, restart, logo  |

Refer to OpenAPI docs at `http://<host>:8000/docs` for request/response schemas.

## MCP Tool Integration

FastApiMCP automatically mounts all endpoints as MCP tools under `/mcp`.  
Use your MCP client to invoke tools by name (e.g., `drop`, `notify`, `toast`, etc.).

## Using MCP Proxy for Clients Without SSE Support (Claude Desktop)

1. Install mcp-proxy:
   ```bash
   uv pip install --user mcp-proxy #for Python
   npm install -g mcp-proxy #for Node.js
   pnpm add -g mcp-proxy #for Node.js
    
   ```

2. On Windows:  
   Edit `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "ultra-mcp-ss": {
         "command": "mcp-proxy",
         "args": ["http://0.0.0.0:8000/mcp"]
       }
     }
   }
   ```

3. On MacOS:  
   Get the path to `mcp-proxy`:
   ```bash
   which mcp-proxy
   ```
   Edit `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "ultra-mcp-ss": {
         "command": "/YOUR/PATH/TO/mcp-proxy",
         "args": ["http://0.0.0.0:8000/mcp"]
       }
     }
   }
   ```

## Setting up MCP-SS in Langflow

To integrate ultra-mcp-ss with Langflow:

<p align="center"> <img src="./img/mcpserver-component.png" alt="drawing" width="300"/></p>

1. Add MCP Server component from the Tool section in Langflow
2. Enable Tool Mode in the component settings
3. Select SSE Mode for real-time communication
4. Enter the MCP SSE URL: `http://0.0.0.0:8000/mcp`
4. Use `http://127.0.0.1:8000` if running using **Docker**.
5. Run the component to establish connection

Once connected, you can use all SmartScreen commands within your Langflow workflows.

## Contributing

1. Fork the repo  
2. Create a feature branch  
3. Submit a pull request  

---

Made with FastAPI & FastApiMCP
