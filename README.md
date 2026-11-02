# logixconfig-ai

A Python tool that turns a plain-English process description (or an equipment
CSV) into validated Rockwell Logix tags, draft documentation, and a starter
.L5X file.

An LLM turns the description into a structured equipment list. Deterministic
templates turn that list into tag names, and a deterministic validator checks
them. The LLM never writes tag names directly.

Status: early development. The generated .L5X has not been tested by importing
into Studio 5000.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
Create .env   # then add your OpenAI API key - OPENAI_API_KEY=
pytest
```

## Trademarks

Not affiliated with or endorsed by Rockwell Automation.
