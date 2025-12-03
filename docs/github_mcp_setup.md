# GitHub MCP setup

This project includes a workspace-level configuration for the [GitHub MCP server](https://github.com/github/github-mcp-server). The setup uses the official Docker image so any MCP-capable host (VS Code, Claude Desktop, Cursor, etc.) can start the server locally with your GitHub token.

## Prerequisites
- Docker installed and running (image is `ghcr.io/github/github-mcp-server`).
- A GitHub personal access token with the scopes you need (minimum: `repo`, `read:org`, `read:packages` if you want registry access).
- An MCP-capable client that can read `.vscode/mcp.json` or accepts the same schema.

## Local (Docker) server
1. Generate a PAT and keep it out of version control.
2. Open the project in your MCP host and allow it to use `.vscode/mcp.json`.
3. When prompted for `github_token`, paste the PAT. The host will run:
   ```
   docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server
   ```
4. (Optional) For GitHub Enterprise Server or ghe.com data residency, set `GITHUB_HOST` in your host config alongside the token.

## Remote server option
If your host supports remote MCP servers with OAuth/PAT headers, you can point it at the hosted endpoint instead of Docker:
```json
{
  "servers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    }
  }
}
```
Supply an `Authorization` header with a PAT if your host does not handle OAuth automatically. See the upstream README for additional toolset flags and advanced configuration.
