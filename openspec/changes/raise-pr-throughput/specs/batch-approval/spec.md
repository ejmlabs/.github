# Spec Delta

## Purpose

Let the owner approve a named set of changes in one pass, without weakening review and without anyone else acting for the owner.

## ADDED Requirements

### Requirement: A batch file names exact items and is the owner's signed action

A batch file MUST list each pull request URL and its exact head commit, the review record and tree hash for each, and the deploy target if any. It MUST carry the owner's SSH signature over its canonical bytes. Only this signature proof is built. Committing the file in a pull request that the owner approves on GitHub is an open option that would need its own build and review. An OK given in chat, mail or any place outside the repository record MUST NOT count. A tool or agent MUST NOT sign it.

#### Scenario: The file is unsigned

- **WHEN** a batch file has no valid owner signature
- **THEN** every tool treats it as empty and reports why

#### Scenario: An item is not named

- **WHEN** a pull request is ready but absent from the batch file
- **THEN** it is not offered to the owner as part of the batch

### Requirement: The owner signs what the owner reads

The signature MUST cover the exact canonical bytes of the items and the deploy, in a file the owner reads before signing, not a digest of it. The verifier MUST run by a fixed absolute path and in a fixed environment, never one found through the caller's `PATH` or changed by the caller's variables or user files.

#### Scenario: A digest is signed instead of the file

- **WHEN** the signature covers a digest line and not the canonical bytes
- **THEN** every tool treats the file as unsigned

#### Scenario: A fake verifier is first on the path

- **WHEN** a program named like the verifier is placed first on `PATH`, or user site files or `PYTHONPATH` are set
- **THEN** none of it runs and a junk signature is refused

### Requirement: The batch is a list the owner clicks through

The batch file MUST NOT authorize any actor but the owner. `/ready`, `/approve`, merge and the resolution of any security concern MUST be performed by the owner on GitHub, one item at a time. A tool MAY read the file and show which entries still match. A tool MUST NOT post a command, approve, merge or resolve a concern.

#### Scenario: The operator reads the file

- **WHEN** the operator identity reads a valid batch file
- **THEN** it may prepare branches and a status view, and it takes no admission, approval or merge step

### Requirement: Each item needs a fresh review

An item MUST NOT be offered for approval unless a review passed on the exact commit that would ship. A pass for any other commit MUST NOT count. A review by an automated reviewer MUST be shown as evidence only and MUST NOT replace the owner's approval.

#### Scenario: The head differs from the reviewed commit

- **WHEN** the pull request head differs from the commit named in the review record
- **THEN** the item leaves the batch and the report says why

### Requirement: A moved head ends the entry

If a pull request head changes after the file is signed, the entry MUST stop covering that item. The only path forward is the carry-over rule: only the base branch moved, the pull request's own patch is identical, and a fresh review passes on the new exact tree. Then a new batch with the carried head is proposed. It MUST NOT take effect until the owner signs it, and the owner still approves on GitHub.

#### Scenario: Only the base branch moved

- **WHEN** a merge of the base branch leaves the patch id unchanged and a fresh review passes on the new tree
- **THEN** a new batch with the carried head is proposed, and it takes effect only when the owner signs it; the existing entry does not cover the moved head

#### Scenario: The patch changed

- **WHEN** the patch id differs from the reviewed one
- **THEN** the item leaves the batch and needs a new signed entry

### Requirement: Rules that never change

Every batch MUST keep these rules: no force-push, no admin merge of any kind (including for reviewer infrastructure), no override of a required check, and the owner's explicit approval on GitHub for the exact items.

#### Scenario: A batch item fails the gate

- **WHEN** the gate blocks an item, whatever it changes
- **THEN** nobody admin-merges or overrides it, and the block is reported

### Requirement: An optional standing class

If the owner grants a standing class, it MUST be written in the operations guide with an exact definition and a deterministic check that tests membership. Items outside the class MUST use a batch entry. A fresh review on the exact commit MUST still be required, and the owner's approval on GitHub MUST still be required.

#### Scenario: A change outside the class

- **WHEN** a pull request does not match the written class
- **THEN** it waits for a batch entry
