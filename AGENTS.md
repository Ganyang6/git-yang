# AI Coding Assistant Memory

## Project: MES Backend (Edge AI Worktime Measurement System)

### Quick Facts
- Backend: Python 3.12 + FastAPI
- Frontend: Node.js 22 + Vue 3 + Vitest
- Database: InfluxDB 2.0
- Cache/Queue: Redis Streams
- Container: Docker Compose + WSL2

## Development Rules

### Before Code Development Tasks
1. Check `.learnings/` for relevant past learnings
2. Review `.github/copilot-instructions.md` if exists
3. Check existing code patterns in similar modules

### After Task Completion
- Log task completion status to `.learnings/` (task summary, what was done, any issues)
- Update related learning entries if new knowledge gained

### TDD Workflow
- RED: Write failing test first (verify it fails for right reason)
- GREEN: Write minimal code to pass test
- REFACTOR: Clean up while keeping tests green
- NO production code without failing tests first

### Code Quality
- Single responsibility principle (modular design)
- Use config/env vars (no hardcoding)
- Use timeout wrappers for blocking I/O
- All data from real sources (no fake data in tests)

## Recent Learnings
See `.learnings/LEARNINGS.md` for accumulated knowledge.
