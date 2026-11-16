# Product performance: project business contract

Template version: `product-contract-v2` (2026-10-26).
V2 explicitly rejects NULL units/revenue, including unsold products: SQL SUM
and ordinary comparisons otherwise hide those violations. Previously copied
trial contracts retain their original version and hashes; this template update
does not change those trial inputs or results.

This is explicit project configuration supplied for the repair workflow. It is
visible to the model and independent of the upstream final pytest evaluator.
It clarifies business choices that the short public ticket leaves open.

1. For valid orders, units are the sum of order-line quantity_ordered. Revenue
   is the stored order-line line_total, including its existing source adjustments.
   Do not substitute quantity * unit_price or another gross/net interpretation.
2. Valid orders exclude the literal statuses CANCELLED, RETURNED and FAILED,
   using the existing staged values without extra case normalization.
3. Keep every product exactly once. Preserve all valid sale quantities and
   revenue when assigning facts to products; a non-NULL product ID can be orphaned.
4. A direct product ID is usable when it exists in the product dimension. When
   it does not, recover through an unambiguous variant ID whose owning product
   exists. Repeated identical variant mappings may be collapsed; conflicting
   mappings must not multiply facts or silently invent ownership. Report unresolved
   assignments. Do not overwrite a valid direct product based on a conflicting
   alternate route without explicit evidence and policy.
5. Count distinct orders at product grain, aggregate variant counts separately,
   use revenue / units for weighted unit price, retain unsold products, and build
   the requested table sorted by revenue descending.
6. Units and revenue must be non-NULL for every product, including zero-valued
   unsold products. Nonzero units require a non-NULL weighted price. A zero-unit
   product may use NULL for its undefined weighted price; no division is required.

The SQL files in this directory expose violations and source/output differences,
not a replacement model. Run check_contracts before and after a repair. Never edit
these checks, the source data, or the independent final tests to obtain a pass.
