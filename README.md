# Care Ladder

Agentic Vision care ladder for the OpenCV AI Competition 2026.

OpenCV cues drive a configurable confirm → Nest/Alexa-style check-in → dial escalation workflow, with privacy blur, pre-event clips, and an incident timeline.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Demo care plan

See `configs/demo_home.yaml`. Emergency rung is **disabled by default** (fail-closed). Demo phones use reserved fiction numbers (`+1212555010x`).

## Tests

```bash
pytest tests/ -v
```
