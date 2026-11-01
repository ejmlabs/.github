## ADDED Requirements

### Requirement: Govern the chess application

The shared gate SHALL admit ejm-chess, check its manifest and root lock versions against VERSION, and allow the canonical JavaScript/TypeScript code scan caller. Its Quality job SHALL require the product-owned executable gate.

#### Scenario: Quality command missing

- **WHEN** an admitted chess change has no executable regular `.github/quality`
- **THEN** Quality fails

#### Scenario: Package version differs

- **WHEN** the chess manifest or root lock version differs from VERSION
- **THEN** Repository standards fails
