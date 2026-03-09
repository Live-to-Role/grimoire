# Grimoire Development Workflow

Guidelines for AI-assisted development on this project. These principles ensure consistent, high-quality contributions.

## Core Philosophy

- **Spec before code** - Understand what we're building before writing anything
- **Test-Driven Development** - Write tests first, always
- **Systematic over ad-hoc** - Process over guessing
- **Evidence over claims** - Verify before declaring success
- **Simplicity as primary goal** - YAGNI (You Aren't Gonna Need It)

---

## The Development Workflow

### 1. Clarify the Request

Before writing any code:

1. **Understand the goal** - What problem are we solving? What's the user trying to accomplish?
2. **Ask clarifying questions** if the request is ambiguous
3. **Identify scope** - What's in scope? What's explicitly out of scope?
4. **Check for existing patterns** - Does similar functionality already exist?

### 2. Write a Brief Spec

For non-trivial changes, document:

```markdown
## What
[One sentence describing the change]

## Why
[The problem this solves]

## How
[High-level approach]

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
```

Get confirmation before proceeding with significant changes.

### 3. Plan the Implementation

Break work into small, verifiable steps:

- Each step should be independently testable
- Prefer many small commits over one large change
- Identify dependencies between steps

### 4. Test-Driven Development (TDD)

Follow the **Red-Green-Refactor** cycle:

1. **Red** - Write a failing test that defines the expected behavior
2. **Green** - Write the minimum code to make the test pass
3. **Refactor** - Clean up while keeping tests green

**Testing priorities for Grimoire:**
- Backend: pytest for API endpoints and services
- Frontend: Component tests for complex UI logic
- Integration: Test API contracts

### 5. Implement Incrementally

- Make one logical change at a time
- Run tests after each change
- Commit working states frequently

### 6. Verify Before Completion

Before declaring work done:

- [ ] All tests pass
- [ ] Manual verification of the feature works
- [ ] No regressions in related functionality
- [ ] Code follows project conventions

---

## Project-Specific Guidelines

### Architecture

```
grimoire/
├── backend/           # FastAPI + SQLAlchemy
│   ├── api/          # Route handlers (thin layer)
│   ├── models/       # Database models
│   ├── schemas/      # Pydantic validation
│   └── services/     # Business logic (test this heavily)
├── frontend/         # React + TypeScript
└── docker/           # Container configs
```

### Backend Conventions

- **Services contain business logic** - Keep API routes thin
- **Pydantic for validation** - All request/response shapes defined in schemas
- **SQLAlchemy models** - Database interactions through models
- **Async where beneficial** - Use async for I/O-bound operations

### Frontend Conventions

- **React patterns** - Hooks, composition, unidirectional data flow
- **No DOM manipulation** - Use React state, not querySelector
- **Mobile-first** - Start with 320px layouts, enhance for desktop
- **Accessibility** - ARIA labels, semantic HTML, keyboard navigation

### Code Style

- **Modular** - Files under 500 lines, functions under 50 lines
- **Single responsibility** - Each module does one thing well
- **Explicit over implicit** - Clear naming, no magic
- **Document the why** - Comments explain reasoning, not what

---

## Debugging Protocol

When something isn't working:

1. **Reproduce** - Can you reliably trigger the issue?
2. **Isolate** - What's the smallest case that fails?
3. **Hypothesize** - What could cause this behavior?
4. **Test the hypothesis** - Add logging, check assumptions
5. **Fix the root cause** - Not the symptom

**Anti-patterns to avoid:**
- Adding workarounds instead of fixing the source
- Changing multiple things at once
- Assuming without evidence

---

## When to Step Back

Pause and reassess if:

- A fix requires more than 2-3 attempts
- The solution feels hacky or overly complex
- You're fighting the framework instead of working with it
- Adding complexity when you should be simplifying

Consider reverting to the last known good state and approaching differently.

---

## Communication

- **Be concise** - State what you're doing and why
- **Surface blockers early** - Don't spin on issues silently
- **Summarize completions** - What was done, what to verify
