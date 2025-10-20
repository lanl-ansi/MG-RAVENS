# RAVENS Data: UML to JSON (template.json) notes

**What is the template?** 
The template (`template.json`) is the canonical, machine-readable specification of the JSON shape that RAVENS models should produce/ingest. The template is akin to a reference manual for how data fitting the RAVENS model should be organized and represented. It answers: *“Given the RAVENS model as presented in (UML) EA diagrams, what does a valid JSON payload look like—what sections exist, which objects live where, which parts are polymorphic (i.e. can be one of several kinds), and where do arrays vs singletons appear?”* 

## Terminology

### Class  
Refers to a UML class (e.g., `Asset`, `Document`). In the EA GUI it’s a displayed element (usually a colored box). In the EA database, it's a row in `t_object` with `Object_Type="Class"`. In our (Python) graph G, each class is a node keyed by its `Object_ID`. *Class* is used throughout this documentation to refer to UML/EA Class elements. We do not use the term *class* to refer to elements in JSON.

### Object  
A construct in the generated JSON template (`"type": "object"`) that defines the shape of data. It’s part of JSON Schema, not a UML Class. Not all UML classes become objects in JSON.

### concrete (and notConcrete) class
A class tagged as either `rootClass` or `embeddedClass` are considered *concrete*. Classes tagged as `substitutableClass`, `containerClass`, and `inheritOnlyClass` are considered *notConcrete*. Useful for algorithmic descriptions later on.

### Subclass

A subclass of **X** is any class that inherits from **X** via a UML Generalization edge (our inheritance graph H uses child → parent). So a subclass of **X** is any child (or transitive child) reachable by going downward from **X** in the reverse of H.


### Lifecycle 
How a thing (class/record) comes into existence, changes over time, and ends.

Concretely, lifecycle covers:
- **Creation** — who/what creates it, and can it be created on its own?
- **Identity** — does it have its own stable ID/name that’s meaningful outside any parent?
- **Updates** — can it be updated independently of other objects?
- **Referencing/Reuse** — do multiple other objects point to the same instance?
- **Deletion/End-of-life** — can it be deleted or archived independently?
- **History** — does it warrant its own audit/version trail?

### Value-like class

A value-like class models data that’s defined by its content, not by a global identity. Think “Address”, “Coordinate”, “TimePoint”, “LimitRange”, “Parameters” — pieces of information that make sense only within their parent object.

Key traits:
- **No global ID**: you don’t look it up by an ID outside its parent; it’s not a standalone record.
- **Equality by value**: two instances are considered the same if their fields are the same.
- **Owned lifecycle**: it’s created/updated/deleted *with* the parent; you typically replace it wholesale rather than patching it independently.
- **Copied rather than referenced**: reuse is fine via duplication; you don’t maintain cross-object references to a single shared instance.
- **Small, cohesive data**: represents a tight cluster of attributes, often conceptually “atomic” to the parent.



---
## Role Definitions 

This section describes how different class roles are identified and used when generating a template from an Enterprise Architect (EA) model.  
Each role is defined both *intuitively* (in plain language) and *algorithmically* (in terms of what how code is designed to identify/validate class types).

### Role matrix

| Role                | Emitted as object? | Can appear at Root level? | Creates anyOf? | Can be owner/container? | Referenced elsewhere? |
|---------------------|--------------------|---------------------------|----------------|-------------------------|-----------------------|
| rootClass           | Yes (canonical)    | Yes (canonical under Root)| No             | No                      | Yes                   |
| embeddedClass       | Yes (inline)       | Sometimes (via owner=Root)| No             | No                      | Rarely                |
| substitutableClass  | Wrapper only       | Yes (where needed)        | Yes            | No                      | N/A                   |
| containerClass      | Yes (container)    | Yes                        | No             | Yes                     | No                    |
| inheritOnlyClass    | No                 | No                         | No             | No                      | N/A                   |


---
### rootClass

#### Intuitition 
A concrete, persistable domain class (magenta in diagrams). It represents “real” things (e.g., Asset, Document) that exist as standalone records.

#### Algorithmic Definition
- Root-ness is designer-defined; there is no deterministic way to infer it from an untagged EA model.
- Placement rule:
  - Define every `rootClass` at `Root` (canonical location). Do not search for a container owner.
  - Elsewhere in the template, refer to it via references as needed.

#### Position in Template (JSON)
- Emit once as a first-level property of `Root`:
  - `"$objectType": "object"`, `"$objectId": "<ClassName>"`, `"type": "object"`, `"properties": {}`
- Other locations should use references with `"$referencePath": "Root/<ClassName>"`.

#### Notes
- Typically a `rootClass` is an anchor of major sub-domains (e.g., assets, locations, documents).
- Generally, these have independent lifecycles and identities (e.g., names/IDs make sense outside any single parent).
- In diagrams, they often have many associations to other classes and appear on multiple diagrams.
- At design time, they’re the classes expected to be reused or referenced from many places.
- When designers choose to tag as `rootClass` (vs. `embeddedClass`), prefer `rootClass` if the class “stands on its own” in the domain.


> **Note:** RAVENS contains a highest-level class named `Root`. This class is special and only exists to serve an organizational function. It is itself not a `rootClass` type.

---

### embeddedClass

#### Intuitition 
A value-like class that lives inside another class. It doesn’t stand alone; its lifecycle is owned by its parent. `embeddedClass`es are green in EA diagrams.

#### Algorithmic Definition
- **Embedded-ness is design-defined.** In other words, there is no deterministic way to identify `embeddedClass` given a set of diagrams/data relationships. It is imposed as a design choice of RAVENS. 
- To place it in the template:
  1) Build the inheritance graph (`H`).
  2) During a Root-down traversal of associations/aggregations, for each embeddedClass `X`, choose its owner as the nearest `containerClass` ancestor on the current traversal branch; if none, owner = `Root`.
  3) Define `X` inline (once) under that owner.

#### Position in Template (JSON)
- Emitted as an inline object under its owner:
  - `"$objectType": "object"`, `"$objectId": "<ClassName>"`, `"type": "object"`, with `"properties": {}`.
- Typically appears nested beneath a `rootClass` in the template (not as a first-level property of `Root`, although some `embeddedClass`es do appear directly beneath `Root`).

> **Note:** Choosing embedded vs. reference is a modeling decision; if an embeddedClass later needs cross-diagram reuse, consider promoting it to a rootClass or introducing a reference pattern.

---

### substitutableClass

#### Intuitition
A polymorphic choice point: “one of these concrete subtypes below.” It marks a spot where the instance may be any of several concrete descendants.

#### Algorithmic Definition
- Using `H` (child→parent) and its reverse:
  - Any `notConcrete` node that is a descendant of either a `rootClass` or an `embeddedClass` (in `H`’s reverse, i.e., reachable going down from those anchors) is `substitutableClass`.
- Precedence: if a node qualifies as both `substitutableClass` and something else, keep `substitutableClass`.

#### Position in Template (JSON)
- Emit a property whose value is an `anyOf` of reference options to concrete descendants that are actually defined elsewhere in the template:
  - 
    ```json
    {
      "anyOf": [
        { "$objectType": "reference", "type": "object", "$objectId": "ConcreteA", "$referencePath": "Root/ConcreteA", "properties": {} },
        { "$objectType": "reference", "type": "object", "$objectId": "ConcreteB", "$referencePath": "Root/ConcreteB", "properties": {} }
      ]
    }
    ```
- Do not define the `substitutableClass` class/node itself as a concrete object; it is only the choice wrapper.
- Populate `anyOf` with only those concrete descendants that are actually emitted in the template (skip types that don’t have a canonical definition).



### containerClass

#### Intuitition
A structural grouping node used to organize related objects and other groups. It is not a persisted record; it shapes hierarchy and scoping.

#### Algorithmic Definition
- In `H` (child→parent), starting from each `rootClass`, walk upward through contiguous `notConcrete` parents; mark all such parents as `containerClass` (unless they were already classified as `substitutableClass`).
- Parents of `embeddedClass` nodes remain `inheritOnlyClass` (not containers).
- Precedence: `substitutableClass` overrides; otherwise qualifying nodes on the contiguous chain above a `rootClass` are `containerClass`.

#### Position in Template (JSON)
- Emit once at its canonical location (often directly under `Root` or under another container):
  - 
    ```json
    { "$objectType": "container", "type": "object", "properties": { } }
    ```
- It contains child properties (embedded objects, other containers, and/or substitutable `anyOf` wrappers). It is not referenced elsewhere.



### inheritOnlyClass

#### Intuitition
A pure base type used only to share attributes with subclasses. It is never instantiated on its own and does not appear as a standalone record.

- contrasted with `substitutableClass`: not a “choice point”; it provides shared fields, while `substitutableClass` defines where a choice among concrete variants (anyOf) is made.
- contrasted with `containerClass`: not a structural owner/grouping node; it doesn’t create a container in the template or determine placement—children inherit from it elsewhere.
- contrasted with `rootClass` / `embeddedClass`: those are concrete and get emitted as objects, whereas `inheritOnlyClass` is abstract in practice and is never emitted directly.


#### Algorithmic Definition
- Build the inheritance graph `H` (Generalization, child→parent).
- Let `concrete` be the set of classes tagged either `rootClass` or `embeddedClass`.
- Let `notConcrete` be the set of classes that don't belong to `concrete` (i.e. "everything that's not emitted")
- Compute:
  - `subs = descendants_of(concrete)` in `H`’s reverse (parents→children).
  - `ancE = ancestors_of(embeddedClass)` in `H` (child→parent).
- A node is `inheritOnlyClass` iff:
  - it is in `ancE` but not in `subs`, or
  - it is any remaining `notConcrete` not classified as `substitutableClass` or `containerClass` (i.e. a catch-all)
- Precedence among classifications: `substitutableClass` > `containerClass` > `inheritOnlyClass`.

#### Position in Template (JSON)
- Not emitted as its own object.
- Its attributes are inherited by concrete descendants that are emitted.
- If a node needs to appear solely to group content, it should instead be modeled/tagged as `containerClass`.


## Generalization Graph (H)

### What it is
`H` is the inheritance graph extracted from the EA model. It contains only UML “Generalization” connectors and encodes type–subtype relationships.

- **Nodes:** all classes in the model (even if they have no generalization edges).
- **Edges:** `child → parent` for each Generalization connector.
- **Reverse graph:** `HR` is the edge-reversed view (used to get descendants efficiently).

### Why we use it
- To classify `notConcrete` classes into `substitutableClass`, `containerClass`, or `inheritOnlyClass`.
- To choose the canonical owner for where a class should be defined in the JSON template (nearest ancestor that’s a `containerClass` on a traversal branch).
- To determine termination (“run out of generalizations below this”) when populating `anyOf` variants.

### How we build it
1. Start from the EA tables; include every class node in `H`.
2. For each connector with `Connector_Type == "Generalization"`, add a directed edge `child → parent`.
3. Build `HR` by reversing all edges of `H`.

### Queries we perform on `H` / `HR`
- `ancestors(H, n)`: all transitive parents of `n` (walk forward in `H`).
- `descendants(HR, n)`: all transitive children of `n` (walk forward in `HR`).
- “Nearest container ancestor on a branch”: BFS upward in `H` from `n`; pick the first node tagged `containerClass` (deterministic tie-break by name if needed).

### UML Role classification with `H`
Let `roots = {nodes tagged rootClass}`, `embedded = {nodes tagged embeddedClass}`, and `yellow = {nodes tagged yellowClass (to be re-typed)}`.

- `substitutableClass`:
  - `substitutable = yellow ∩ descendants(HR, roots ∪ embedded)`
- `inheritOnlyClass` (from embedded chains):
  - `inherit_from_embedded = (yellow ∩ ancestors(H, embedded)) − substitutable`
- `containerClass` (yellow chains above roots):
  - climb upward in `H` from each root through contiguous yellow parents; collect them  
  - `containers = (yellow parents on these chains) − substitutable`
- Remaining yellow:
  - `inheritOnly = yellow − substitutable − inherit_from_embedded − containers`
- Precedence when overlaps occur:
  - `substitutableClass` > `containerClass` > `inheritOnlyClass`

### Assumptions and edge cases
- We expect single inheritance (at most one generalization parent). If multiple parents exist, we still build `H` but may need project-specific tie-break rules.
- Cycles in generalization should not exist; if found, they are flagged during validation.
- Association/Aggregation connectors are not part of `H` (they’re used for traversal from `Root`, not for inheritance logic).

### Why we use the Generalization graph (H) instead of the full graph (G)
`H` does not consider connector types that are not `Generalization`s. I.e., it exlcudes `Aggregation`s, `Association`s, `Composition`s, etc.

- **Different semantics.**  
  Generalization = *is-a (type/subtype)*.  
  Association/Aggregation = *has-a / references / wiring*.  
  Role classification (substitutable/container/inheritOnly) and `anyOf` variants depend on *type* ancestry, not on “has-a” links.

- **Unambiguous direction & acyclicity.**  
  `H` is directed `child → parent` and should be acyclic, which makes “ancestors/descendants” well-defined. The full graph (with associations) can be cyclic and bidirectional, which breaks ancestry reasoning.

- **Correct polymorphism.**  
  `anyOf` for a substitutable base must include its *subclasses*. Only `H` tells you the valid variant set; associations would include unrelated neighbors.

- **Deterministic ownership.**  
  Picking the “nearest container ancestor” for where a class should be defined is a *type* decision. Walking up associations would conflate usage with taxonomy.

- **Clean termination.**  
  The “stop when you run out of generalizations below this” rule is naturally expressed on `HR` (the reversed inheritance graph). Associations provide no such boundary.

- **Separation of concerns.**  
  We use Associations/Aggregations to traverse from `Root` to lay out properties (template shape).  
  We use Generalization to:
  - classify yellow classes (substitutable/container/inheritOnly),
  - choose canonical owners,
  - build `anyOf` variant lists.

In short: we use `H` for **what a class *is*** (type hierarchy), and use Associations/Aggregations for **how classes *relate*** (property/reference layout).





