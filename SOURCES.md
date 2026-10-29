# Sources and rights

Source: U.S. Energy Information Administration, EIA-923 annual final historical plant operations for 2018-2024; snapshot retrieval date recorded per archive. Official landing page https://www.eia.gov/electricity/data/eia923/ identifies all data prior to 2025 as final. Historical data can still be revised; this study fixes inspected bytes rather than claiming original release vintages.

Official archive links follow https://www.eia.gov/electricity/data/eia923/archive/xls/f923_2018.zip through f923_2024.zip, as linked on the landing page. Ordinary HEAD requests for the first and last archives returned 200 before the protocol; no fuel/generation values were inspected.

Definitions: https://www.eia.gov/survey/form/eia_923/instructions.pdf. Net generation is gross generation less station use, in MWh, and may be negative. Combined-cycle CA steam output can have no corresponding fuel entry; aggregate the related technology components before eligibility. The current instructions support definition checks but do not alone prove every older workbook uses identical headers or reporting rules; inspect each source header and documentation.

Rights: https://www.eia.gov/about/copyrights_reuse.php permits attributed data reuse; third-party protected works and logos have separate restrictions. Publish minimal attributed federal aggregate facts and original analysis only. Full workbooks, guides, logos/photos and excluded fields stay outside public Git. No EIA endorsement.

Mathematical method: an explicit algebraic symmetric two-factor identity and outside-cohort bridge, with both orderings retained and independently checked. This is an established decomposition form, not a new estimator or causal attribution.
