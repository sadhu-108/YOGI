"""Results Assembler — Implements IResultAssembler for packaging screening results."""

import math
from typing import Any, Mapping, Optional, Sequence

from yogi.core.contracts.results import ColumnDefinition, IResultAssembler, QueryResultPayload
from yogi.results.columns import DEFAULT_SUMMARY_COLUMNS, RANK_COLUMN_ALIASES, build_column_definition


def _clean_value(val: Any) -> Any:
    """Normalize NaN values to None while preserving None and valid numbers/strings."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return val


class ResultAssembler(IResultAssembler):
    """Assembles calculation, ranking, and selection outputs into a QueryResultPayload.

    Strictly adheres to presentation packaging:
    - Does NOT filter, rank, select, sort, or slice records.
    - Preserves the incoming record order established upstream.
    - Projects specified or default summary columns.
    - Normalizes missing and NaN values to None.
    - Attaches summary metadata and column definitions.
    """

    def assemble(
        self,
        records: Sequence[Mapping[str, Any]],
        columns: Optional[Sequence[str]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> QueryResultPayload:
        """Package selected records and project columns for presentation."""
        # 1. Determine projected column keys
        if columns is not None:
            projected_keys: list[str] = list(columns)
        else:
            # Discover all distinct keys present across records preserving first-seen order
            all_record_keys: list[str] = []
            seen: set[str] = set()
            for r in records:
                for k in r.keys():
                    if k not in seen:
                        seen.add(k)
                        all_record_keys.append(k)

            # Check which DEFAULT_SUMMARY_COLUMNS exist
            present_defaults = [c for c in DEFAULT_SUMMARY_COLUMNS if c in seen]

            if len(present_defaults) >= 2:
                # Include standard summary columns + any active dynamic RANK_* columns
                rank_keys = [c for c in all_record_keys if c.startswith("RANK_") and c not in present_defaults]
                projected_keys = present_defaults + rank_keys
            elif all_record_keys:
                # Arbitrary or non-standard custom records
                projected_keys = all_record_keys
            else:
                # Empty records with columns=None
                projected_keys = list(DEFAULT_SUMMARY_COLUMNS)

        # 2. Build strongly typed ColumnDefinition objects
        col_definitions: list[ColumnDefinition] = [build_column_definition(k) for k in projected_keys]

        # 3. Clean and project record fields in preserved input order
        cleaned_rows: list[dict[str, Any]] = []
        for rec in records:
            row: dict[str, Any] = {}
            for k in projected_keys:
                val = rec.get(k)
                if (val is None or (isinstance(val, float) and math.isnan(val))) and k in RANK_COLUMN_ALIASES:
                    for alt_key in RANK_COLUMN_ALIASES[k]:
                        alt_val = rec.get(alt_key)
                        if alt_val is not None and not (isinstance(alt_val, float) and math.isnan(alt_val)):
                            val = alt_val
                            break
                row[k] = _clean_value(val)
            cleaned_rows.append(row)

        # 4. Resolve metadata and cardinality counts
        meta: dict[str, Any] = dict(metadata or {})
        rec_count = len(records)
        universe_count = int(meta.get("universe_count", rec_count))
        qualified_count = int(meta.get("qualified_count", rec_count))
        selected_count = int(meta.get("selected_count", rec_count))

        return QueryResultPayload(
            universe_count=universe_count,
            qualified_count=qualified_count,
            selected_count=selected_count,
            rows=cleaned_rows,
            columns=col_definitions,
            metadata=meta,
        )
