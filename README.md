<div align="center">

# Pustaka

**MCP server that searches thesis full text from 75+ Indonesian university repositories.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License: AGPLv3](https://img.shields.io/badge/License-AGPLv3-red.svg)](LICENSE)
[![Universities](https://img.shields.io/badge/Universities-75%2B-orange)](repositories.json)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple)](https://modelcontextprotocol.io)

</div>

**Pustaka** is an MCP server that searches thesis repositories across 75+ Indonesian universities (PTN, PTS, Polytechnics) using OAI-PMH harvesting and HTML scraping. It detects which theses are full text by analyzing PDF content directly.

Port of [pencari-skripsi-indonesia](https://github.com/yingtze/pencari-skripsi-indonesia) (MIT) by Yingtze.

## Quick Start

```bash
pip install "pustaka-mcp[pdf]"
pustaka
```

### With uvx

```bash
uvx --from pustaka-mcp pustaka.exe
```

### Claude Desktop config

```json
{
  "mcpServers": {
    "pustaka": {
      "command": "uvx",
      "args": ["--from", "pustaka-mcp", "pustaka.exe"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `search_thesis` | Search by keyword, filter by university/type/province. Returns full/partial/locked status. |
| `list_universities` | List all supported universities, filter by type (PTN/PTS) or province. |
| `analyze_pdf` | Deep PDF content analysis. Detects chapters, estimates page count, checks access. |
| `search_and_analyze` | Combined search and PDF analysis in one call. Slower but returns accurate status immediately. |

### Resources

- `skripsi://universities` - all universities as JSON
- `skripsi://stats` - repository statistics

## Status Meanings

| Status | Meaning |
|--------|---------|
| **FULL** | Chapters 1, 3, 4, 5 and bibliography detected inside the PDF |
| **PARTIAL** | Some chapters found, incomplete or HTML-only detection |
| **LOCKED** | PDF exists but requires login or embargo |
| **UNKNOWN** | Cannot determine automatically |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PUSTAKA_DELAY` | `1.2` | Delay between requests (seconds) |
| `PUSTAKA_WORKERS` | `5` | Number of parallel threads |
| `PUSTAKA_NO_CACHE` | `0` | Set to `1` to disable local cache |

## Requirements

- Python 3.10+
- `pdfminer.six` (optional, for PDF content analysis)

```bash
pip install pustaka-mcp[pdf]
```

Without `pdfminer.six`, the server still works but uses HTML-only detection.

## Original Work

Port of [pencari-skripsi-indonesia](https://github.com/yingtze/pencari-skripsi-indonesia) by Yingtze, released under MIT License. The original provides the repository configurations, OAI-PMH harvesting logic, HTML parsers, and PDF analysis heuristics.

## License

**AGPL-3.0-only** - This port. See [LICENSE](LICENSE).

The original [pencari-skripsi-indonesia](https://github.com/yingtze/pencari-skripsi-indonesia) is MIT licensed.
