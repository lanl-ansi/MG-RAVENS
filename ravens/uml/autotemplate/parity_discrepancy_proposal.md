# UML / Hand Parity Proposal

This document is meant to support a project discussion about why the current UML-derived auto template and the manually curated hand template still disagree, and what kinds of changes would close those gaps.

It is intentionally framed as a proposal, not as a final recommendation to edit either the hand template or the UML without review.

## Scope And Inputs

It is based on:

- the original hand template
- the current auto template generated from the kept simplified UML diagrams
- the current smoke/comparison tooling
- the manual UML rulings we already made during investigation

## Current Snapshot

### Baseline Parity (Raw)

These numbers compare the original hand template against the current auto template before filtering anything out of scope.

| Metric | Count | Meaning |
| --- | ---: | --- |
| Shared exact schemas | 864 | Hand and auto already agree exactly here. |
| Missing in auto | 85 | Hand expects these schemas, but auto does not currently reproduce them. |
| Only in auto | 89 | Auto produces these schemas, but hand does not currently include them. |
| Hand schema count | 949 | Total schemas produced from the original hand template. |
| Auto schema count | 953 | Total schemas produced from the current auto template. |
| Targeted builder regressions | 0 / 188 | The current remaining problem is no longer the targeted builder logic. |

### Planning Snapshot (Excluding `Inf*` / `Mkt*`-Driven Problems)

For current planning, `Inf*` / `Mkt*`-driven mismatches are treated as out of scope. In practice, this removes:

- `17` `missing_in_auto` schema rows tied directly to excluded `Inf*` content or to hand expectations that currently depend on `Inf*` diagrams
- `1` `only_in_auto` schema row tied to mixed `Root` / `Inf*` scope (`CommunityFacility`)

Using that filtered view, the working comparison is:

| Metric | Count | Meaning |
| --- | ---: | --- |
| Shared exact schemas | 864 | Hand and auto already agree exactly here. |
| Missing in auto, excluding `Inf*` / `Mkt*` scope | 68 | Hand still expects these schemas, and they are not explained away by `Inf*` / `Mkt*` scope. |
| Only in auto, excluding `Inf*` / `Mkt*` scope | 88 | Auto still produces these schemas, and they are not explained away by `Inf*` / `Mkt*` scope. |
| In-scope disagreement total | 156 | These are the remaining rows worth prioritizing after removing `Inf*` / `Mkt*` scope issues. |
| Targeted builder regressions | 0 / 188 | The current remaining problem is no longer the targeted builder logic. |

For prioritization, this filtered table is the one to use.

A large share of the remaining disagreement is no longer “the template builder is still broken.” Instead, we have:

- hand expectations that are broader than the current kept UML diagrams
- classes or relationships that only live on `Root` diagrams, or are not explicit enough on the kept diagrams
- hand-only unions or reverse relationships that are not explicitly modeled in the kept simplified diagrams

## Highlights / To Discuss

This section is meant to be the quick meeting agenda. It pulls together the main questions that came up during the latest review pass.

### Quick Status

- The `auto-builder` currently looks stable for the issues we were actively debugging: targeted regressions are `0 / 188`.
- The hand template already picked up three clear additive updates:
  - `ApplicationSettings` -> added `AlgorithmObjectives`
  - `Switch` -> added `Disconnector` and `DisconnectingCircuitBreaker`
  - `OperationalLimitSet.OperationalLimitValue` -> added the six missing operational-limit variants
- The remaining high-value questions are now mostly about whether the hand template, the UML diagrams, or both should change.

### Priority Discussion Topics

| Priority | Topic | Current Read | Decision Needed |
| --- | --- | --- | --- |
| 1 | `PowerSystemResource.AssetDatasheet` | This does not look like a simple missing-hand-variants problem. Hand narrows datasheet targets by equipment context, while auto broadens many `AssetDatasheet` references to the whole `AssetInfo` family. The transformer diagrams support the hand-style narrowing pretty well. | Decide whether the UML is supposed to allow broad `AssetInfo` references everywhere, or whether `AssetDatasheet` should narrow by equipment context. If narrowing is desired, decide whether that should be expressed in UML or taught to the `auto-builder`. |
| 2 | `ProposedAssetSet.ProposedAssets[]` | Under the current UML, the `auto-builder` looks reasonable. One diagram shows `ProposedAssetSet.ProposedAssets -> ProposedAsset`, and another shows the specialized subclasses under `ProposedAsset`. Auto is merging those facts. | Decide whether `ProposedAssetSet.ProposedAssets` is supposed to allow base `ProposedAsset`, or only the specialized subclasses. Also review whether the floating `ProposedAsset` / `ProposedAssetSet` pair on the `Groups` diagram is a UML error or diagram-cleanup issue. |
| 3 | `ACLineSegment.PerLengthImpedance` | Hand already models `PerLengthImpedance` as the family/container and already includes `PerLengthSequenceImpedance` and `PerLengthPhaseImpedance`. The remaining difference is that auto also treats `PerLengthImpedance` itself as a selectable target. | Decide whether `PerLengthImpedance` itself should be selectable at this path, or whether hand is intentionally correct to list only the more specific choices. |
| 4 | Hand-only narrowings already documented | Several remaining hand-vs-UML mismatches still look like hand is broader than the kept diagrams: `ProposedBatteryUnitOption.InverterController`, `GeographicalRegion` vs `SubGeographicalRegion`, `ConformLoadGroup` / `NonConformLoadGroup` energy-consumer ownership, `PredictedEmissions.Location`, `ArTapStep.TapChanger`, and `ActivityRecord.EnvironmentalEvent`. | Decide which of these should eventually become UML updates, and which should remain documented hand-only expectations. No immediate hand removals are assumed. |
| 5 | `ApplicationSettings` inherited-property propagation | Auto propagates `ApplicationSettings.Application` and `ApplicationSettings.Settings` into each variant. Hand currently keeps a lighter raw-template representation, but this is not causing schema-level mismatches. | Decide whether hand should be manually updated for raw-template consistency, or whether this can stay as-is since schema parity is already fine. |

### Suggested Meeting Order

1. Confirm that the `auto-builder` is no longer the main blocker.
2. Decide the rule for `PowerSystemResource.AssetDatasheet`.
3. Decide the rule for `ProposedAssetSet.ProposedAssets[]`.
4. Decide whether `ACLineSegment.PerLengthImpedance` is intentionally selective in hand.
5. Review the documented hand-broader-than-UML cases and decide which should become UML work items.

### Documented Hand-Narrowing Candidates

These are still worth keeping in the proposal because they explain several obvious disagreements between hand and the kept UML.

However, they should currently be treated as discussion items, not as immediate edits to the hand template. The present working assumption is:

- keep the current hand structure in place for now
- document the obvious hand-narrowing candidates clearly
- review them before making any removals or simplifications

With that framing, the practical discussion order is:

| Priority | Family / Issue | Why It Is A Good Discussion Candidate | Potential Hand Change To Discuss | Likely Payoff If Adopted |
| --- | --- | --- | --- | --- |
| 1 | `ProposedBatteryUnitOption.InverterController` and its control-mode variants | The kept diagrams do not currently support this structure, and the hand template is carrying a whole unsupported polymorphic family here | Remove or narrow the hand `InverterController` branch under `ProposedBatteryUnitOption` | High; this should remove `7` current missing rows in one family |
| 2 | `GeographicalRegion` vs `SubGeographicalRegion` unions and broader targets | We already verified that the kept diagrams consistently point these relationships to `SubGeographicalRegion`, not a broader union | Narrow the hand template from `GeographicalRegion` or `GeographicalRegion | SubGeographicalRegion` to `SubGeographicalRegion` where the kept diagrams already say that | Medium-high; this should clean up the region-family mismatches, including the `CoincidentPeakPrices` case |
| 3 | `ConformLoadGroup.EnergyConsumers` and `NonConformLoadGroup.EnergyConsumers` | The kept diagrams support the shared `LoadGroup` relationship, but not the subtype-owned versions the hand template currently models | Remove the subtype-owned arrays and keep the shared `LoadGroup.EnergyConsumers` modeling instead | Medium; this should remove `2` hand-only pointer-array mismatches with fairly contained edits |
| 4 | `PredictedEmissions.Location` | The kept diagrams do not currently support `ProposedSiteLocation` as an alternative target in this context | Narrow the hand reference from `Location | ProposedSiteLocation` to the supported target | Low-medium; likely resolves `1` clean union mismatch |
| 5 | `ArTapStep.TapChanger` subtype union | The kept diagrams support `TapChanger`, but not the `RatioTapChanger | PhaseTapChanger` union the hand template expects | Narrow the hand reference to base `TapChanger` | Low-medium; likely resolves `1` clean union mismatch |
| 6 | `ActivityRecord.EnvironmentalEvent` | The hand template currently assumes array/object structure that the kept UML does not clearly support | Remove the unsupported array structure or reshape it to the simpler supported form | Low-medium; likely resolves `1` mismatch, but the edit is a little less obvious than the union narrowings above |

These rows should be read as “documented potential simplifications,” not “approved hand edits.”

### What Is Not An Easy Hand Fix

These should not be the first hand edits:

| Bucket | Why To Defer |
| --- | --- |
| Real auto-only classes already supported by kept UML | These require hand growth, not hand narrowing, so they are more manual and easier to get wrong without a clear curation decision |
| Most synthetic auto-only schemas | These are downstream artifacts and often disappear only after the real class-level decisions are settled |
| Large Type B families such as curve subclasses, switching-action subclasses, and tap-changer support classes | These are much more naturally UML-side decisions than quick hand-template edits |
| `Root`-only families such as `Message` | These are still a scope decision, not yet an “obvious” hand correction under the current rules |

### Missing Variants Already In Auto

This is a better place to start if the current strategy is “add to hand first, remove nothing for now.”

I compared the raw `anyOf` variant sets in [template.json](/mnt/x/research/ravens/repo/mg-ravens/ravens/lib/template.json) and [template_auto.json](/mnt/x/research/ravens/repo/mg-ravens/ravens/lib/template_auto.json), then pulled out the cases where auto is a strict superset of hand at the same path.

After the recent manual additions, there are now only `3` path-level strict-superset cases left:

| Priority | Family / Path Pattern | Variants Present In Auto But Missing In Hand | Why This Is A Good Starting Point |
| --- | --- | --- | --- |
| 1 | `PowerSystemResource.AssetDatasheet` under conductor/equipment paths | `AssetInfo`, `PowerTransformerInfo`, `ShuntCompensatorInfo`, `SwitchInfo`, `TapChangerInfo`, `TransformerEndInfo`, `TransformerTankInfo`, `WireAssemblyInfo` | Review before editing. This no longer looks like a simple “missing variants in hand” case. It looks more like a question about whether the UML is supposed to allow broad `AssetInfo` references everywhere, or whether those references should narrow by equipment context. |
| 2 | `ProposedAssetSet.ProposedAssets[]` | `ProposedAsset`, `ProposedBatteryUnit`, `ProposedBranch`, `ProposedEnergyProducerAsset` | Review before editing. Under the current UML, the auto-builder looks reasonable here. The remaining question is whether the UML and hand are supposed to allow base `ProposedAsset` at this path, or whether the diagrams should be changed to restrict it to specialized subclasses. |
| 3 | `ACLineSegment.PerLengthImpedance` | `PerLengthImpedance` | Review before editing. Hand already models `PerLengthImpedance` as the family/container, so the remaining difference is not as obviously a missing business variant. |

At this point, none of the remaining `3` path-level strict-superset cases look like obvious hand edits. All three are better treated as review/discussion items before changing hand.

#### Additive Cases To Review Before Editing

| Family / Path Pattern | Why It Is Not As Obvious As The Earlier Additions | Current Recommendation |
| --- | --- | --- |
| `PowerSystemResource.AssetDatasheet` under conductor/equipment paths | The individual info classes are already aligned at schema level, so this is not really about whether classes like `PowerTransformerInfo`, `TransformerTankInfo`, `TransformerEndInfo`, `TapChangerInfo`, or `WireAssemblyInfo` exist. The real disagreement is path-specific: hand narrows `AssetDatasheet` by equipment context, while auto broadens many `PowerSystemResource.AssetDatasheet` references to the whole `AssetInfo` family. The transformer diagrams support the hand-style interpretation pretty well, so this currently looks more like a question about what the UML is supposed to allow, or whether the auto-builder should learn to narrow these references by context, than a missing hand-variant problem. | Keep this on the discussion list. Do not bulk-add the broad auto union into hand without first deciding whether `AssetDatasheet` should stay broad or narrow by equipment context. |
| `ProposedAssetSet.ProposedAssets[]` | The current UML gives two signals: the `ProposedAssets` diagram shows the subtype family under `ProposedAsset`, and the `Groups` diagram separately shows a direct `ProposedAssetSet.ProposedAssets -> ProposedAsset` association. The auto-builder is merging those two facts, which makes its inclusion of base `ProposedAsset` look reasonable. At the same time, the `Groups` diagram presents `ProposedAsset` and `ProposedAssetSet` as a disconnected floating pair, which may itself be a UML error or at least a diagram that needs cleanup. | Keep this on the discussion list. Treat the auto-builder as reasonable under the current UML, and decide instead whether the UML and hand should allow base `ProposedAsset` here or whether the diagrams should be tightened to specialized subclasses only. |
| `ACLineSegment.PerLengthImpedance` | Hand already includes `PerLengthImpedance` as the owning family/container and already carries `PerLengthSequenceImpedance` / `PerLengthPhaseImpedance` beneath it. The remaining auto-side difference is that auto also treats `PerLengthImpedance` itself as a selectable reference target. Given the UML coloring/role here, this may be intentional rather than an omission in hand. | Keep this on the discussion list for now rather than editing hand immediately. |

#### Applied Manual Hand Additions

| Family | Change Made | Notes |
| --- | --- | --- |
| `ApplicationSettings` | Added `AlgorithmObjectives` as a hand `anyOf` variant | This matches the UML/auto presence of `AlgorithmObjectives` as an intermediate class under `AlgorithmProperties` and before `BusVoltageObjective`. |
| `Switch` | Added `Disconnector` and `DisconnectingCircuitBreaker` as hand `anyOf` variants | This matches the UML/auto switch-family variants and cleanly closed two auto-only class mismatches without affecting targeted checks. |
| `OperationalLimitSet.OperationalLimitValue` | Added `ActivePowerImbalanceLimit`, `ApparentPowerImbalanceLimit`, `ReactivePowerImbalanceLimit`, `ReactivePowerLimit`, `SwitchingActionLimit`, and `VoltageImbalanceLimit` as hand `anyOf` variants | This matches the UML/auto operational-limit family and cleanly closed six auto-only class mismatches without affecting targeted checks. |

#### Open Question To Review

- `ApplicationSettings` in auto propagates inherited `ApplicationSettings.Application` and `ApplicationSettings.Settings` properties into each variant, while hand currently keeps a lighter representation for those variants. This looks consistent with prior guidance that auto is correct here, but it is still a manual-followup question whether hand should be edited to propagate those inherited properties as well.

## High-Level Read

The disagreement now breaks into four main types:

The type counts below are left in their raw form for traceability. For current prioritization, the filtered planning snapshot above is the metric to use.

| Type | Count | Direction | Typical Cause | Usual Resolution |
| --- | ---: | --- | --- | --- |
| Hand expects content that is not currently supported by valid simplified diagrams | 23 | Hand -> Auto | Root-only, excluded-diagram-only, or already-verified hand-beyond-diagram expectations | Decide whether to promote that content into kept UML diagrams, or explicitly keep it out of scope |
| Hand expects content that is absent from the current kept diagrams or not represented clearly enough | 62 | Hand -> Auto | Classes, variants, or relationships are not on kept simplified diagrams, or are not explicit enough to drive generation | Add classes, labels, or associations to kept UML diagrams if the hand behavior is intended |
| Auto contains real UML-supported classes that hand does not currently include | 28 | Auto -> Hand | Hand coverage is narrower than what the kept UML diagrams already support | Manual curation decision; this is usually not a UML problem |
| Auto contains synthetic schema helpers that hand does not currently include | 61 | Auto -> Hand | These are schema decomposition artifacts such as containers, arrays, and polymorphic helper schemas | Usually defer until the real class-level decisions are settled |

## Type A: Hand Expects Content That Is Not Currently Supported By Valid Simplified Diagrams

This is the cleanest “UML-side fix if desired” bucket because we already investigated these by hand.

### A1. Verified Relationship / Union Gaps

These are the places where the hand template expects a relationship or union that the kept simplified diagrams do not currently support clearly enough.

| Problem Class | Hand Expects | Current UML Gap | Proposed UML-Side Change | Notes |
| --- | --- | --- | --- | --- |
| `ConformLoadGroup.EnergyConsumers` | A `ConformLoad` pointer array owned by `ConformLoadGroup` | `ConformLoadGroup` appears with a generalization to `LoadGroup`, but no visible labeled relation to `ConformLoad` on a valid kept diagram | Add a visible labeled association from `ConformLoadGroup` to `ConformLoad` on a kept simplified diagram if this ownership is intended | If not intended, keep the shared `LoadGroup` relationship instead |
| `NonConformLoadGroup.EnergyConsumers` | A `NonConformLoad` pointer array owned by `NonConformLoadGroup` | Same issue as above, but for `NonConformLoad` | Add a visible labeled association from `NonConformLoadGroup` to `NonConformLoad` on a kept simplified diagram if intended | This should be decided alongside the conform-load case |
| `ActivityRecord.EnvironmentalEvent` | An array of `EnvironmentalEvent` objects under `ActivityRecord` | `ActivityRecord` appears on `Outages`, but the connection is not a clear visible labeled association in the kept diagrams | Add a visible labeled association between `ActivityRecord` and `EnvironmentalEvent` on a kept diagram | If this relationship is not meant to be supported, leave it out |
| `EnergyAreaConnector.EnergyAreas` | An `EnergyArea` pointer array under `EnergyAreaConnector` | `EnergyAreaConnector` only appears on `InfFacilities` today | Move `EnergyAreaConnector` and the labeled `EnergyAreas` relationship into a kept simplified diagram if intended | Otherwise treat it as intentionally out of scope |
| `GeographicalRegion` vs `SubGeographicalRegion` targets | Hand uses broader `GeographicalRegion` targets and a `GeographicalRegion | SubGeographicalRegion` union | The kept diagrams consistently point these relationships to `SubGeographicalRegion`, and do not show the broader union or the reverse relationship clearly enough | If the broader hand behavior is intended, add explicit kept-diagram support for that union and direction | This affects `EconomicProperty`, `CapacityPrices`, `LocationalMarginalPrices`, `CoincidentPeakPrices`, `ProposedSiteLocation.Region`, and the reverse `SubGeographicalRegion.Region` expectation |
| `PredictedEmissions.Location` | A `Location | ProposedSiteLocation` union | No kept simplified diagram shows `ProposedSiteLocation` as an alternative location target in the needed context | Add a kept-diagram relationship that explicitly supports `ProposedSiteLocation` as an alternative location target if intended | Right now this looks hand-broader-than-UML |
| `ArTapStep.TapChanger` subtype union | A `RatioTapChanger | PhaseTapChanger` union | `ArTapStep -> TapChanger` exists, but the subtype classes are not on valid kept diagrams | Bring `RatioTapChanger` and `PhaseTapChanger` into kept diagrams and make the intended subtype support explicit | If only the base `TapChanger` is intended, no UML change is needed |
| `ProposedBatteryUnitOption.InverterController` modes | An `InverterController` polymorphic object with multiple control-mode variants | `ProposedBatteryUnitOption` is present, but the `InverterController` association and control-mode variants live outside kept simplified diagrams | Bring `InverterController` and its intended control-mode variants into kept simplified diagrams, with visible associations | This is one of the clearest “hand knows more than kept UML” cases |

### A2. Root-Only Or Excluded-Diagram Content

These disagreements are structurally simpler. The question is mostly whether this content should be promoted into the kept simplified diagrams at all.

| Family | Where It Lives Today | What Hand Expects | General UML-Side Resolution |
| --- | --- | --- | --- |
| `CommunityFacility` family | `Root` plus `InfCommunityFacilities` | `CommunityFacility` split into `GridFacility` / `NonGridFacility`, plus related facility-service structure | Decide whether the `InfCommunityFacilities` content should be promoted into kept simplified diagrams |
| `EquivalentBranch` / `EquivalentLine` under `CommunityFacility` | `InfCommunityFacilities` | Branch-related facility structure and related wrapper schemas | Same decision as above: either promote that family or leave it out of simplified scope |
| `ACDCConverter` | `InfDCConductors` | Hand includes it, auto excludes it under current kept-diagram policy | Decide whether to promote `InfDCConductors` content into kept simplified diagrams |
| `Message` family | `Root` only | A polymorphic array of `Error`, `Warning`, `Info`, and `Debug` message objects | Decide whether `Root`-only message polymorphism is authoritative enough to move into kept diagrams |

## Type B: Hand Expects Content That Is Absent From The Current Kept Diagrams Or Not Represented Clearly Enough

This is the biggest bucket. These rows do not currently look like builder bugs. They mostly look like “if the hand behavior is truly intended, the kept UML diagrams need to say more.”

This bucket has `62` rows. The most useful way to discuss it is by family.

| Family / Theme | Example Entries | Likely UML-Side Resolution |
| --- | --- | --- |
| Curve subclasses not on kept diagrams | `EmissionCurve`, `FuelCostCurve`, `HeatRateCurve`, `PriceCurve`, `RampRateCurve`, `ReactiveCapabilityCurve`, `ShutdownCurve`, `StartRampCurve`, `StartUpCostCurve`, `StartUpTimeCurve`, `VsCapabilityCurve` | Bring the intended curve subclasses into the kept diagrams where their owner relationships are supposed to be supported |
| Generator cost / schedule support | `GenUnitOpCostCurve`, `GenUnitOpSchedule` | Add the missing cost/schedule classes and visible associations to the kept diagrams if the hand behavior is intended |
| Switching-action subclasses | `ClampAction`, `ClearanceAction`, `ControlAction`, `CutAction`, `EnergyConsumerAction`, `EnergySourceAction`, `JumperAction`, `MeasurementAction`, `TagAction`, `VerificationAction` | Bring the intended switching-action subclasses into kept switch/action diagrams if hand coverage should include them |
| Tap-changer support classes | `SvTapStep`, `TapChangerControl`, `TapChangerRatio` | Add these classes and their relationships to kept tap-changer / transformer diagrams if the hand behavior should remain authoritative |
| Power-electronics / rotating-machine support | `BatteryResponseCharacteristic`, `GridFollowingProtection`, `GridFormingProtection`, `PowerElectronicsOperatingMode`, `RotatingMachineResponseCharacteristic`, `PhaseConnectionDetail` | Add the intended classes and labels to kept energy-producer diagrams if these behaviors should be supported |
| Miscellaneous group / topology / facility gaps | `Bay`, `Plant`, `ConformLoadSchedule`, `CoincidentPeakPrices`, `EquivalentEquipment` | Review one family at a time; these are real gaps, but they do not all have the same likely UML change |

### What To Do With This Bucket

This is probably the most important project-priority discussion, because it is the biggest remaining disagreement source and it directly answers:

- which hand behaviors are supposed to stay authoritative
- which classes or relationships belong in the kept simplified diagrams
- which things are acceptable to leave outside simplified scope

## Type C: Auto Already Contains Real UML-Supported Classes That Hand Does Not Yet Include

This bucket is different. These are not obvious UML problems. They are mostly curation decisions about whether the hand template should grow to match content that the kept diagrams already support.

There are `28` real auto-only classes or root objects.

### C1. Real Auto-Only Classes On Kept Non-Root Diagrams

These are the strongest candidates for review, because the UML already supports them.

| Domain | Example Classes Already In Auto | Why They Matter | Likely Resolution |
| --- | --- | --- | --- |
| Operational limits | `OperationalLimitSet` | The operational-limit variants are now aligned, but the kept UML still produces the root set object itself | Decide whether hand should add the root set object |
| Conductors / switching / equipment | `ACLineSegment`, `WireSegment`, `PerLengthPhaseImpedance`, `PerLengthSequenceImpedance`, `EarthFaultCompensator`, `Ground`, `GroundingImpedance`, `SeriesCompensator` | These are valid kept-diagram classes already making it into auto | Usually a hand-coverage decision, not a UML fix |
| Groups / locations / topology | `GeographicalRegion`, `SubGeographicalRegion`, `Location`, `PopulationGroup`, `ConnectivityNode`, `TopologicalNode`, `BaseVoltage`, `DCLine` | These are core kept-diagram classes that auto already emits | Good candidates for “should hand expand here?” review |
| Energy producers / controls / settings | `PowerElectronicsConnection`, `PowerElectronicsUnit`, `EnergySource`, `StaticVarCompensator`, `RegulatingControl`, `AnalysisResultData`, `BasicIntervalSchedule` | These are already supported by kept diagrams | Manual hand-curation decision |

### C2. Real Auto-Only Classes That Are Root-Only Or Mixed-Scope

| Class | Current Scope | Likely Discussion |
| --- | --- | --- |
| `Message` | `Root` only | Do we want `Root`-only content to count toward parity? |
| `DynamicsFunctionBlock` | `Root` only | Same question as above |
| `CommunityFacility` | `Root` plus excluded `InfCommunityFacilities` | Depends on whether the community-facility family should be promoted into kept diagrams |

## Type D: Auto-Only Synthetic Schema Helpers

These are usually downstream schema artifacts, not direct UML modeling decisions.

There are `61` of them:

| Synthetic Type | Count | What It Usually Means | Recommendation |
| --- | ---: | --- | --- |
| `_Container` | 27 | Hash-table / container schemas created during decomposition | Do not drive UML changes from these directly |
| `_anyOfContainer` | 10 | Polymorphic object helper schemas | Revisit after the real class-level decisions are made |
| `_anyOfPointer_anyOfContainer` | 8 | Polymorphic reference helper schemas | Same as above |
| `_PointerArray` | 9 | Arrays of pointers emitted from supported relationships | Usually secondary to the underlying class/association decision |
| `_Array` | 7 | Array helper schemas | Usually secondary to the underlying class decision |

Examples include:

- `ActivityRecord_Pointer_anyOfContainer`
- `Fault_anyOfContainer`
- `AnalysisResultData_PointerArray`
- `ConnectivityNodeContainer_Container`

These should usually be treated as follow-on artifacts. They are not the place to start UML edits.

## Recommended Discussion Order

If the goal is to make the UML and hand align intentionally, the highest-signal review order is:

1. Decide whether `Root`-only and `Inf*` / `Mkt*` content should count as part of the target scope.
2. Review the verified relationship / union gaps in **Type A1**.
3. Prioritize which families in **Type B** are actually supposed to remain in the hand template long-term.
4. Review the valid-diagram auto-only real classes in **Type C** and decide whether hand should grow there.
5. Ignore most of **Type D** until the real class and relationship decisions are settled.

## Short Recommendation

If the project chooses a UML-first strategy, the cleanest interpretation is:

- treat the hand-edit experiment as evidence, not as a final change set
- roll back the hand-template edits
- use this document to decide which UML diagrams should be expanded, relabeled, or promoted into the kept simplified set
- only after those UML decisions, rerun the auto-template path and see which hand mismatches remain

That approach keeps the hand template in its current “target behavior” role while still using the recent debugging work to make the disagreement classes understandable.
