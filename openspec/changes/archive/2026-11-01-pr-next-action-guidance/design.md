## Design

Two metadata-only jobs use the existing caller and the live API. The first follows admission and the second follows finalization. A bounded retry detects observed body and head changes; GitHub does not offer an atomic body update, so a later external edit can still race. Independent check completion and description edits do not trigger refreshes.
