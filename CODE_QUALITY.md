# Code Quality

This project uses `ruff`, `pytest`, and `basedpyright` for different parts of the quality loop.

## Current Checks

- `ruff check .`: linting for selected Python rules.
- `ruff format --check .`: formatting.
- `pytest`: behavioral regression tests.
- `basedpyright`: static type analysis, currently scoped to `src` only.

## Basedpyright Strategy

The project was not originally written as a fully typed codebase, so a strict `basedpyright` run produces many findings at once. Most are not immediate bugs; they identify dynamic boundaries that the type checker cannot prove safe.

The main sources of noise are:

- SQLite rows, which enter the code as dynamically typed row mappings.
- JSON/provider responses, where shape validation happens at runtime.
- Plain `dict` return values from DB-facing helper functions.
- Optional third-party dependencies with incomplete or broad type information.
- Test fixtures and mocks, which are intentionally dynamic.

## Initial Decision

Start by checking production source only:

```toml
[tool.basedpyright]
include = ["src"]
exclude = ["tests"]
```

Tests can be added later after the production code baseline is under control.

## Recommended Rule Posture

Prefer keeping high-signal checks strict:

```toml
reportArgumentType = "error"
reportOperatorIssue = "error"
reportAttributeAccessIssue = "error"
reportOptionalMemberAccess = "error"
reportReturnType = "error"
reportAssignmentType = "error"
reportCallIssue = "error"
```

Consider relaxing these during the initial adoption phase if the noise blocks progress:

```toml
reportMissingTypeArgument = "warning"
reportAny = "none"
reportExplicitAny = "none"
reportUnknownVariableType = "none"
reportUnknownMemberType = "none"
reportUnknownArgumentType = "none"
reportUnknownParameterType = "none"
reportMissingParameterType = "none"
reportUnusedCallResult = "none"
reportUnannotatedClassAttribute = "none"
```

Do not suppress rules just to make output look clean. Prefer fixing high-signal findings first, especially where a function boundary can be typed with a dataclass, `TypedDict`, or explicit runtime validation.

## Ratcheting Plan

1. Keep `basedpyright` scoped to `src`.
2. Drive source errors toward zero.
3. Type the most-used database boundaries with dataclasses or `TypedDict`s.
4. Keep warnings visible but non-blocking until the error baseline is stable.
5. Revisit warning-level rules one group at a time.
6. Add tests to the check only after source code has a stable baseline.

## Current Direction

The first useful fixes are not broad casts everywhere. They are targeted shape improvements, such as replacing mixed dictionaries with explicit types and making callback contracts match their annotations.

The goal is not maximum typing ceremony. The goal is to catch realistic defects without making everyday changes painful.
