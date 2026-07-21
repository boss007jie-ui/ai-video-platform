# IR-1 / IR-2 Boundary

The repository began as the clean-room IR-1 skeleton and IR-2 Foundation
Registry V1. Under `FTG-0-20260720-001`, FT-1 now adds eight independently
callable clean-room Skill RC implementations while preserving those foundation
boundaries.

Each Skill may contain its owned implementation, `SKILL.md`, public Interface
or CLI, internal adapters, package files, and offline tests. Cross-Skill use is
limited to the target Skill package export, root `interface` module, or `cli`
module; private implementation imports remain forbidden. Provider adapters are
fake or rejecting only, network access and Provider SDKs remain forbidden, and
no runtime source may depend on a Legacy path.

Product Knowledge is the only allowed Product Library writer, and Viral
Research & Asset Collection is the only allowed Research Library writer. Their
offline and temporary test adapters do not authorize creation or mutation of
the external canonical Libraries. No Skill may call Apify, access the network,
download real media, read Legacy Source Libraries, or use a real Provider under
the current gate.

The Foundation Registry remains exactly one Envelope identity plus eleven
payload IDs. Fast Track business artifacts live only in the separate versioned
Business Artifact Registry; future additions require the applicable shared
Contract gate and must not change the Foundation identity set.

This state is offline RC evidence only. Provider smoke remains unauthorized,
and the platform is not declared Production Ready.
