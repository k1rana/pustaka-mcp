<div align="center">

# 📚 Pustaka

**MCP server — search thesis full text from 75+ Indonesian university repositories.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License: AGPLv3](https://img.shields.io/badge/License-AGPLv3-red.svg)](LICENSE)
[![Universities](https://img.shields.io/badge/Universities-75%2B-orange)](repositories.json)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple)](https://modelcontextprotocol.io)

</div>

---

**Pustaka** is an MCP server that searches thesis repositories across 75+ Indonesian universities — PTN, PTS, and Polytechnics — via OAI-PMH harvesting and HTML scraping. It detects which theses are truly full-text (Bab 1 through Daftar Pustaka) by analyzing PDF content directly.

This is a port of [pencari-skripsi-indonesia](https://github.com/yingtze/pencari-skripsi-indonesia) (MIT) by Yingtze — original credit below.

---

## Quick Start

```bash
# Install
pip install "pustaka-mcp[pdf]"

# Run (stdio transport)
pustaka
```

### With uvx

```bash
uvx pustaka-mcp
```

### Claude Desktop config

```json
{
  "mcpServers": {
    "pustaka": {
      "command": "uvx",
      "args": ["pustaka-mcp"]
    }
  }
}
```

---

## Tools

| Tool | Description |
|------|-------------|
| `search_thesis` | Search by keyword, filter by university/type/province. Returns results with full/partial/locked status. |
| `list_universities` | List all supported universities, filter by type (PTN/PTS) or province. |
| `analyze_pdf` | Deep PDF content analysis — detects chapters inside the document, estimates page count, checks access. |
| `search_and_analyze` | Combined search + PDF analysis in one call. Slower but returns accurate status immediately. |

### Resources

- `skripsi://universities` — all universities as JSON
- `skripsi://stats` — repository statistics

---

## Status Meanings

| Status | Meaning |
|--------|---------|
| ✅ **FULL** | Chapters 1, 3, 4, 5 and bibliography detected inside the PDF |
| 🟡 **PARTIAL** | Some chapters found — incomplete or HTML-only detection |
| 🔴 **LOCKED** | PDF exists but requires login/embargo |
| ⚪ **UNKNOWN** | Cannot determine automatically |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SKRIPSI_DELAY` | `1.2` | Delay between requests (seconds) |
| `SKRIPSI_WORKERS` | `5` | Number of parallel threads |
| `SKRIPSI_NO_CACHE` | `0` | Set to `1` to disable local cache |

---

## Requirements

- Python 3.10+
- `pdfminer.six` (optional, for PDF content analysis — recommended)

```bash
pip install pustaka-mcp[pdf]
```

Without `pdfminer.six`, the server works but uses HTML-only detection (less accurate).

---

## Structure

```
├── src/pustaka/
│   ├── __init__.py         ← version
│   ├── models.py           ← data models + scoring
│   ├── pdf_analyzer.py     ← PDF content analysis
│   ├── engine.py           ← OAI-PMH + HTML scraping engine
│   └── server.py           ← FastMCP server
├── tests/
│   └── test_mcp.py         ← 35+ unit tests
├── repositories.json       ← 75+ university configs
├── .vscode/
│   └── PORT_FROM_PREVIOUS_REPO.md  ← port notes
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## Original Work

This project is a port of **[pencari-skripsi-indonesia](https://github.com/yingtze/pencari-skripsi-indonesia)** by **Yingtze**, released under the **MIT License**. The original work provides the core repository configurations, OAI-PMH harvesting logic, HTML parsers, and PDF analysis heuristics that make this possible.

Without Yingtze's groundwork of cataloging 75+ Indonesian university repositories and building the scraping infrastructure, this MCP server would not exist.

---

## License

**AGPL-3.0-only** — This port. See [LICENSE](LICENSE).

The original [pencari-skripsi-indonesia](https://github.com/yingtze/pencari-skripsi-indonesia) is MIT licensed.
