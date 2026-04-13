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

### Baseline Parity

These numbers compare the original hand template against the current auto template.

| Metric | Count | Meaning |
| --- | ---: | --- |
| Shared exact schemas | 855 | Hand and auto already agree exactly here. |
| Missing in auto | 85 | Hand expects these schemas, but auto does not currently reproduce them. |
| Only in auto | 98 | Auto produces these schemas, but hand does not currently include them. |
| Hand schema count | 940 | Total schemas produced from the original hand template. |
| Auto schema count | 953 | Total schemas produced from the current auto template. |
| Targeted builder regressions | 0 / 188 | The current remaining problem is no longer the targeted builder logic. |

A large share of the remaining disagreement is no longer “the template builder is still broken.” Instead, we have:

- hand expectations that are broader than the current kept UML diagrams
- classes or relationships that only live on `Root`, `Inf*`, or `Mkt*` diagrams
- hand-only unions or reverse relationships that are not explicitly modeled in the kept simplified diagrams

## High-Level Read

The disagreement now breaks into four main types:

| Type | Count | Direction | Typical Cause | Usual Resolution |
| --- | ---: | --- | --- | --- |
| Hand expects content that is not currently supported by valid simplified diagrams | 23 | Hand -> Auto | Root-only, excluded-diagram-only, or already-verified hand-beyond-diagram expectations | Decide whether to promote that content into kept UML diagrams, or explicitly keep it out of scope |
| Hand expects content that is absent from the current kept diagrams or not represented clearly enough | 62 | Hand -> Auto | Classes, variants, or relationships are not on kept simplified diagrams, or are not explicit enough to drive generation | Add classes, labels, or associations to kept UML diagrams if the hand behavior is intended |
| Auto contains real UML-supported classes that hand does not currently include | 37 | Auto -> Hand | Hand coverage is narrower than what the kept UML diagrams already support | Manual curation decision; this is usually not a UML problem |
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

There are `37` real auto-only classes or root objects.

### C1. Real Auto-Only Classes On Kept Non-Root Diagrams

These are the strongest candidates for review, because the UML already supports them.

| Domain | Example Classes Already In Auto | Why They Matter | Likely Resolution |
| --- | --- | --- | --- |
| Operational limits | `OperationalLimitSet`, `ActivePowerImbalanceLimit`, `ApparentPowerImbalanceLimit`, `ReactivePowerImbalanceLimit`, `ReactivePowerLimit`, `SwitchingActionLimit`, `VoltageImbalanceLimit` | These are already on kept operational-limit diagrams | Decide whether hand should add them |
| Conductors / switching / equipment | `ACLineSegment`, `WireSegment`, `PerLengthPhaseImpedance`, `PerLengthSequenceImpedance`, `EarthFaultCompensator`, `Ground`, `GroundingImpedance`, `Disconnector`, `DisconnectingCircuitBreaker`, `SeriesCompensator` | These are valid kept-diagram classes already making it into auto | Usually a hand-coverage decision, not a UML fix |
| Groups / locations / topology | `GeographicalRegion`, `SubGeographicalRegion`, `Location`, `PopulationGroup`, `ConnectivityNode`, `TopologicalNode`, `BaseVoltage`, `DCLine` | These are core kept-diagram classes that auto already emits | Good candidates for “should hand expand here?” review |
| Energy producers / controls / settings | `PowerElectronicsConnection`, `PowerElectronicsUnit`, `EnergySource`, `StaticVarCompensator`, `RegulatingControl`, `AnalysisResultData`, `AlgorithmObjectives`, `BasicIntervalSchedule` | These are already supported by kept diagrams | Manual hand-curation decision |

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
