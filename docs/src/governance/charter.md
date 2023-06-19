# MG-RAVENS API Governance Charter

The following document serves as the guiding charter of the organization guiding the research and development of the API proposed by the MG-RAVENS Project funded by the Department of Energy Office of Electricity Microgrid Research and Development Program, herein called the RAVENS API.

The following groups are the named organizational structures for the development of the RAVENS API.

- [Steering Committee](#steering-committee)
- [Working Group](#working-group)
- [Core Developers](#core-developers)

## Steering Committee

The purpose of the Steering Committee is to provide guidance on the development of the API by developing a vision and providing approval for releases of the API.

The Steering Committee will be led by a Chair, who will

- lead meetings of the Steering Committee, and
- resolve votes by the Committee in the event that they are tied.

Current membership of the Steering Committee will be recorded [in this repository](./steering_committee.md).

### Assigning Representatives

If a Steering Committee member anticipates periods of inactivity, e.g., due to personal or professional conflicts requiring their attention, they may assign a representative to act on their behalf in meetings and during votes by notifying the Steering Committee in writing. The Steering Committee will identify the representative for the record in recorded votes.

In cases where a member of the Steering Committee anticipates extremely long absences, Steering Committee members are encouraged to consider formally nominating their representative for Steering Commmittee membership and renouncing their own membership on the Steering Committee.

### Adding Steering Committee Members

New members may be added to the Steering Committee at any time with an affirmative vote of a [supermajority](#supermajority) of the Steering Committee.

### Removing Steering Committee Members

Members may be removed from the Steering Committee under the following conditions:

- at the request of the member, or
- by affirmative vote of a [supermajority](#supermajority) of the members of the Steering Committee whose membership is not in question.

Members of the Steering Committee shall consider removal of a fellow member in the event of a breaking of the Code of Conduct when brought to their attention when rising to the level of enforcement of a Permanent Ban.

Members of the Steering Committee shall consider removal of a fellow member of the Steering Committee in the event that member has been absent for a prolonged period and has not designated a representative, such that their absence is preventing the Committee from performing regular business.

## Working Group

The purpose of the Working Group is to provide feedback throughout the API development. Working Group members shall be parties who are interested in the development of the RAVENS API.

The Steering Committee will maintain a Working Group Mailing List, to which various communications may be sent. The Steering Committee will remove Working Group members from the List at the request of the member.

We ask those members of the Working Group to:

- Participate in semiannual meetings of the API team, which we intend to hold virtually and record for members who are unable to attend live.
  - Meetings will be advertised via the Working Group Mailing List.
- Respond to [Requests for Information (RFIs)](#request-for-information) about their data needs, software that they currently use, and microgrid program software they would be interested in using, which will help inform the development of the API.
  - RFIs may be solicited via the Working Group Mailing List and/or via a GitHub Discussion.
- Respond to [Requests for Comment (RFCs)](#request-for-comment) on major API release candidates.
  - RFCs may be solicited implictly via a GitHub Pull Request tagged as a major or minor change, and/or explicitly via a GitHub Discussion linked to the proposed changes.
  - RFCs for major changes may be advertised via the Working Group Mailing List.
- Identify data or accompanying tools that your organization might need us to include in our development for your organization to adopt any part of the API in the future.

Members may be added to the Working Group at any time at the request of any member of the Steering Committee. Those not currently in the Working Group interested to join may contact any member of the Steering Committee to request they be added to the Working Group.

The Steering Committee may advertise the **name** and **organization** of Working Group members [in this repository](./working_group.md), but may not reveal contact information or other Personal Identifiable Information.

## Core Developers

- Core developers will be designated by the Steering Committee, and be given the "Role: Write" in this repository by the repository administator(s).
- Core developers will execute the vision of the Steering Committee in the creation of the API.
- Core developers will request approval to incorporate new functionality or to substantially change existing functionality of the API from the Steering Committee.
- Core developers may incorporate bug fixes into the API as needed without explicit approval from the Steering Committee.
- Core developers may accept changes to the API via Pull Requests, where
  - new functionality or substantive changes to existing functionality requires approval from the Steering Committee, and
  - bug fixes at their discretion.

## API Release Approval

Releases of the API will follow the [Semantic Version](https://semver.org/) scheme, i.e., MAJOR.MINOR.PATCH, where

- MAJOR releases incorporate incompatible, or **breaking**, changes,
- MINOR releases incorporate backwards-compatible, or non-breaking, functionality, and
- PATCH releases incorporate backwards-compatible bug fixes.

Core developers may release PATCH versions without explicit approval from the Steering Committee.

MINOR and MAJOR releases require consent from the Steering Committee through one of the following two methods:

- [unanimous consent](#unanimous-consent), or
- [simple majority](#simple-majority).

As part of the release process, the Working Group will be given the opportunity to voice their concerns, opinions, etc. through a RFC, i.e., on the GitHub Pull Request or on a connected GitHub Discussion thread. The Steering committee will consider feedback carefully and request Core Developers to make changes based on that feedback at their discretion.

## Making Changes to the Charter

Changes can be made to this Charter with an affirmative vote consisting of a [supermajority](#supermajority) of the Steering Committee.

## Definitions

### Request for Comment

A _request for comment_ (RFC) is a process whose purpose is to solicit qualified feedback on a technical proposal, in this case an API release candidate. It collects all feedback and ideas in one place and serves as a record of decision making.

### Request for Information

A _request for information_ (RFI) is a process whose purpose is to collect information about capabilities and needs of the community. An RFI is used to gather information to inform decisions, and is non-binding.

### Simple Majority

_Simple majority_ is defined herein as 50% + 1. In the situation where a simple majority is required a poll in a GitHub Discussion will be used to record the vote by members of the Steering Committee, or their assigned representative in their absence.

### Supermajority

_Supermajority_ is defined herein as 60% + 1. In the situation where a supermajority is required a poll in a GitHub Discussion will be used to record the vote by members of the Steering Committee, or their assigned representative in their absence.

### Unanimous consent

_Unanimous consent_ is a situation in which no member present objects to a proposal. In the context of approving a MINOR or MAJOR release, Pull Requests will remain open for a period of one week for members of the Steering Committee, or their assigned representative in their absence, to provide objections. If an objection is made, a vote must be recorded.

## License

LA-UR-23-26030
