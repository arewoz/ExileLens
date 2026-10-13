# Loot Filters and Analyze Build (Experimental)

Both features are included in ExileLens 1.0 scope. Their navigation badges describe maturity; native PoE2 acceptance and wider gameplay validation are still required. Item Check, privacy choices and optional market consent retain their existing behavior.

## Loot Filters

Choose a **profile**, choose a **theme**, inspect the preview, then select **Generate & Install**. **Recommended** is the default. A full general filter works without a connected PoB build, Build Intelligence, market prices or network access.

| Profile | Purpose |
| --- | --- |
| Relaxed | Broad visibility, quieter common loot |
| Recommended | Balanced visibility; ordinary rares and low waystones stay quiet |
| Strict | Less common loot, with strong crafting bases retained |
| Very Strict | Top rare bases and quieter utility drops |
| Uber Strict | Strong opportunities and protected value with minimal clutter |

Existing Endgame settings migrate to Very Strict. Campaign visibility remains automatic. All eight Visual V4 themes are retained: Void Gold, Blood Sigil, Arcane Prism, Verdant Relic, Emberforge, Abyssal Covenant, Eternal Empire and Wraeclast Ashes.

The preview uses the same sample when you change profiles or themes. **Reroll** explicitly changes it. Visible, quiet and hidden counts help compare strictness. Hover a label to inspect its first matching rule and supporting evidence. Native rendering may differ from the approximation.

Personalization is optional. **General** uses the complete generic policy. **Personalized** uses a current measurement. **Analysis outdated** asks for re-analysis and uses the general policy meanwhile. **Partial personalization** retains opportunities supported by the available evidence. An unidentified base is a candidate, not a confirmed upgrade; filter rules cannot inspect its hidden modifiers. Offline trade relevance is a heuristic, not a live price.

Select **Choose folder** if detection cannot find the PoE2 directory. ExileLens uses the Windows Documents location, including redirected Documents, then `My Games/Path of Exile 2`. Files are named by strictness: `ExileLens_Relaxed.filter`, `ExileLens_Recommended.filter`, `ExileLens_Strict.filter`, `ExileLens_Very_Strict.filter` and `ExileLens_Uber_Strict.filter`. Changing theme or build updates that profile's file; other profiles stay separately selectable. An existing `ExileLens_Test.filter` remains untouched and is still detected until the selected profile is installed. Select the new profile file in PoE2 after installing. ExileLens refuses to replace a same-named file without its ownership header. User-created filters remain untouched. A validated file replaces the previous version atomically; a failed verification restores the previous working bytes.

**Selected**, **Generated** and **Installed** configurations are shown separately. **Check installation** re-reads the file; hashes and paths are available in **Details & diagnostics**. Select the file in PoE2 and use the game's filter refresh control after installing. ExileLens cannot confirm that the client loaded or reloaded those bytes.

After game patches, use an updated ExileLens data snapshot and regenerate. Base names come from an evidence-backed ground-base registry, not the entire PoB base universe. Unknown ground items receive a separate safety rule. Unsupported or ambiguous native names are excluded; incompatible data blocks generation. A static validator cannot prove native client compatibility or detect every live game-data change.

For suspicious loot decisions, record base, native class, rarity, item level, unidentified tier if known, area level, profile/theme and personalization state. Include the preview's matching rule and file/rule hashes from Details. For client parser errors, include the exact line and client version. Avoid sharing private build exports or local paths unless needed and deliberately redacted.

## Analyze Build

Open **Analyze Build** and select **Analyze Build** or **Re-analyze**. The header identifies the build and freshness. The page leads with strongest measured responses, the most actionable issue and top upgrade opportunities. Measurements describe responses to specific tested increments in PoB; they do not guarantee an in-game improvement or compare unlike increments on a universal per-point scale.

Exact tested changes and confidence remain in tooltips and **Show measurement details**. **Evidence & limitations** contains health and coverage. Select an upgrade opportunity for its reasons; Search Intent and JSON export appear with measurement details. Full paths and technical identifiers remain in details. Sensitivity and Build Priorities calculations are unchanged.

Filter-specific analysis can additionally measure Armour and Evasion through the existing production scheduler. The normal Analyze Build action retains its standard probe catalog, cancellation, cache, confidence and freshness contracts.
