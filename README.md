# MG-RAVENS API

![lab-logos.png](docs/src/assets/lab-logos.png)

This is the home of the MG-RAVENS Project, stay tuned for updates.

## Building Application Programming Interfaces for Grid Modeling

MG-RAVENS is an ambitious new project led by Los Alamos National Laboratory, in collaboration with the National Renewable Energy Laboratory, Sandia National Laboratories, Lawrence Berkely National Laboratory, and the National Rural Electric Cooperative Association, funded by the Department of Energy, Office of Electricity (OE), Microgrid R&D Program.
The project’s goal is to develop a standardized communication protocol, or Application Programming Interface (API), for advanced modeling and analysis tools for the power grid. While the API will be demonstrated on research tools developed within OE’s Microgrid R&D Program, it will be designed from the ground up to be extendable, maintainable, and agile, responding to the needs of researchers, users, and developers alike to ensure the broader community’s needs are considered and incorporated. The resulting API will be available with a permissible open-source license, so that users of all types can adopt our standards, significantly broadening the audience for advanced grid modeling tools among researchers, utilities, and commercial entities.

|                                                                                                                                        ![RAVENS-Notional-Workflow.png](docs/src/assets/RAVENS-Notional-Workflow.png)                                                                                                                                         |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------: |
| **Application Programming Interfaces (APIs) enable the creation of dynamic analysis workflows. Here we illustrate a workflow for microgrid design that will be used to demonstrate our proposed API. Different tools are used in each step of the analysis, interacting with the data they need, and outputting to a standard format, e.g., CIM IEC 61970.** |

Our vision is to enable the dynamic combination of different modeling capabilities into new workflows for advanced analysis of the power grid, analogous to what HELICS has achieved for co-simulation.
We invite you to participate in the building of this next generation of grid modeling and analysis capabilities by getting directly involved in our governance.

## [Governance Structure](docs/src/governance/charter.md)

To ensure long-term success, we are establishing a governance structure from the outset. Taking inspiration from other well-known open-source organizations, our governance consists of three groups: core developers, a working group, and a steering committee.

Details can be found under [docs/src/goverance/charter.md](docs/src/governance/charter.md)

### [Steering Committee](docs/src/governance/steering_committee.md)

The primary role of the Steering Committee is to assign core developers and approve releases of the API. The Committee is also responsible for synthesizing information and feedback from the community, ensuring the community’s needs are represented in the final product, engaging in outreach, and providing regular demonstrations of the API and its associated tools.

### [Working Group](docs/src/governance/working_group.md)

The Working Group is open to anybody interested in standardizing the way that grid modeling and analysis software interacts. We only ask that members commit to providing information and feedback to aid in the creation of these standards, by doing the following:

- Participating in bi-annual meetings, through direct attendance or by providing feedback on the minutes and supporting materials released after the meeting.
- Providing constructive input and feedback on the schemas, through Requests for Comment (RFCs) and Requests for Information (RFIs).
- Providing feedback on Governance, including recommendations for new members for the Steering Committee.
- Recommending ways to test the schemas, API, and/or supporting tools, and/or identify paths for adoption within your own organizations, including informing us of the features that would be critical to future adoption.

Details and updates as they come will be found here on GitHub.

## Developer Guide

The following dependencies are required:

- Python >= 3.12
- mdbtools == 1.0.0 (for Python dependency "pandas-access")
- Nodejs >= 20.15.1 (for d3.js UML Rendering)

## Contact

To request to join the Working Group, or for any other questions, please contact us at [ravens@lanl.gov](mailto:ravens@lanl.gov).

LA-UR-23-23229

## Copyright

© 2024. Triad National Security, LLC. All rights reserved.
This program was produced under U.S. Government contract 89233218CNA000001 for Los Alamos National Laboratory (LANL), which is operated by Triad National Security, LLC for the U.S. Department of Energy/National Nuclear Security Administration. All rights in the program are reserved by Triad National Security, LLC, and the U.S. Department of Energy/National Nuclear Security Administration. The Government is granted for itself and others acting on its behalf a nonexclusive, paid-up, irrevocable worldwide license in this material to reproduce, prepare. derivative works, distribute copies to the public, perform publicly and display publicly, and to permit others to do so.

Copyright Reference Number: O4764
