# logixconfig-ai

A Python tool that turns a plain-English process description (or an equipment CSV) into validated Rockwell Logix tags, draft documentation, and a starter .L5X file.

An LLM turns the description into a structured equipment list. Deterministic templates turn that list into tag names, and a deterministic validator checks them. The LLM never writes tag names directly.

Status: early development. The generated .L5X has not been tested by importing into Studio 5000.

## L5X output

The .L5X follows one profile: a v24-style, non-safety project for a 1756-L71 controller, with controller-scoped tags, one MainProgram with an empty MainRoutine and one continuous MainTask.

Based on Rockwell's Logix 5000 Controllers Import/Export Reference Manual (1756-RM014D): the tag element layout, the order of child elements inside a tag, and the data formats (raw hex followed by decorated values).

Unverified:

- Importing the file into Studio 5000.
- The controller skeleton values (revisions, module identity, chassis size, and project settings)
- The tag name rules and the 512 character description limit. These are not stated in 1756-RM014D; see the Logix 5000 Controllers Common Procedures manual(1756-PM001).

## Roadmap

- A profile for newer Studio 5000 versions.
- Safety (GuardLogix) projects, which need the tag Class attribute and safety
  project settings.
- Other controllers, such as CompactLogix.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
Create .env   # then add your OpenAI API key (OPENAI_API_KEY=) and OpenAI model (OPENAI_MODEL=)
pytest
```

## API

The API is local-only by default: `logixconfig-api` binds to 127.0.0.1:8000. Results are stored in a local SQLite file (`logixconfig.db`, or the `DATABASE_URL` environment variable). Download files are generated on demand from the stored data, nothing is written to disk.

```bash
logixconfig-api                      # http://127.0.0.1:8000, docs at /docs

curl -s -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"description": "Tank 1 has a level transmitter and one transfer pump.", "controller_name": "Skid01"}'

curl -s http://127.0.0.1:8000/generations/<id>
curl -s -O http://127.0.0.1:8000/generations/<id>/download/tags.csv
curl -s -O http://127.0.0.1:8000/generations/<id>/download/Skid01.L5X
```

Downloadable files are `tags.csv`, `docs.md`, `io_list.csv`, and `<controller_name>.L5X`. A description must be 1 to 2000 characters. If the pipeline cannot produce a valid equipment list, `/generate` returns 422 with the validation issues.

To require a token, set `LOGIXCONFIG_API_TOKEN` and send it with every request:

```bash
curl -s -H "Authorization: Bearer $LOGIXCONFIG_API_TOKEN" http://127.0.0.1:8000/generations/<id>
```

Set a token before binding to any other address with `--host`.

## Trademarks

Not affiliated with or endorsed by Rockwell Automation.
