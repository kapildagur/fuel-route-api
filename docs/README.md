# Documentation

| Order | Document | Status |
| --- | --- | --- |
| 1 | [Design](design.md): requirements, architecture, planning algorithm, errors, test plan | Draft |
| 2 | [Architecture decision records](adr/README.md) | Accepted |

## Diagrams

Sources are PlantUML files in [diagrams](diagrams); each includes `style.iuml`, and `make diagrams` renders the committed SVGs.

| Diagram | UML type | Used in |
| --- | --- | --- |
| [component-fuel-route-api](diagrams/component-fuel-route-api.svg) | Component | [Design, section 4](design.md#4-architecture) |
| [sequence-fuel-plan](diagrams/sequence-fuel-plan.svg) | Sequence | [Design, section 4.1](design.md#41-request-flow) |
| [activity-fuel-planner](diagrams/activity-fuel-planner.svg) | Activity | [Design, section 4.2](design.md#42-planning-algorithm) |
