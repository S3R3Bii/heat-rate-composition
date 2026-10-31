# Separate v2 native source check

The fixed identity-only quarantine finds 18 plant identities with 102 conflict/duplicate events across the seven saved source workbooks. It removes 736 selected-fuel rows across all years and retains 27,842 rows with unambiguous keys/plant-year contexts. The quantities in ambiguous excluded rows are not combined. The original plant 56668 source conflict remains unresolved and its failure receipt is preserved.

An independent openpyxl scan derives the same whole-plant quarantine from all valid source-row identities/classifications and selected source keys. A separate lxml reader reconciles every retained raw XML field/token/hash with the public projection. The check reports 814,042 source/projected field conditions and 55,684 independent numeric conversion conditions. Maximum conversion difference is 7e-10, within the fixed 1e-6 absolute plus 1e-15 relative bound. Those bounds concern the workbook reader, not measurement accuracy.

There are 28,578 native selected-fuel rows before quarantine; 18 plant identities/736 rows are excluded conservatively without assuming that duplicate records are disjoint. No national-generation coverage fraction is known from ambiguous quantities. This is source-quality evidence, not a physical judgment about those plants.

All captured source bytes are reused; no new retrieval, decomposition, held outcome or influence score has been run. The public projection retains CHP/geographic/diagnostic records so subsequent explicit filters and exclusions can be replayed. Group completeness, aggregate positivity and fixed primary matched-plant support are still required before analysis. No release is counted.
