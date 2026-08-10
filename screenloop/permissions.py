"""The permission catalogue.

A permission is a point in the code, so the catalogue lives in code. Only the
roles built from it and the grants handed out are stored in the database. A row
naming a permission no gate checks is invisible rubbish; a gate naming a
permission no row defines fails at runtime. Keeping the catalogue here makes
both mismatches a test failure instead -- see `tests/test_permissions.py`.

`viewer`, `operator` and `admin` survive as built-in roles holding exactly the
permissions those roles had when they were levels in an integer comparison.
Migrating must not change what anybody can do.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    key: str
    section: str
    title: str
    description: str


CATALOG: tuple[Permission, ...] = (
    # --- screens ---
    Permission("tv.view", "tvs", "View TVs", "See configured screens and their playback state."),
    Permission("tv.command", "tvs", "Command TVs", "Play, stop, restart, mute, and resume playback."),
    Permission("tv.manage", "tvs", "Manage TVs", "Add, edit, delete, import, export, and detect screens."),
    Permission("tv.scan", "tvs", "Scan for TVs", "Run DLNA discovery across the local network."),
    # --- media ---
    Permission("media.view", "media", "View media", "See uploaded clips and their transcode status."),
    Permission("media.upload", "media", "Upload media", "Add new clips."),
    Permission("media.manage", "media", "Manage media", "Toggle silent and compressed transcodes."),
    Permission("media.delete", "media", "Delete media", "Remove clips and their transcoded copies."),
    Permission("media.share", "media", "Share media", "Publish a clip to the shared library, or take it back."),
    # --- playlists ---
    Permission("playlist.view", "playlists", "View playlists", "See playlists and their contents."),
    Permission("playlist.edit", "playlists", "Edit playlists", "Create playlists and change their items."),
    Permission("playlist.delete", "playlists", "Delete playlists", "Remove playlists."),
    Permission("playlist.assign", "playlists", "Assign playlists", "Put a playlist onto a screen or a group."),
    Permission("playlist.share", "playlists", "Share playlists", "Publish a playlist to the shared library, or take it back."),
    # --- transcoding ---
    Permission("transcode.view", "transcode", "View transcode jobs", "See the transcode queue."),
    Permission("transcode.rebuild", "transcode", "Rebuild transcodes", "Re-run a transcode job."),
    Permission("transcode.manage", "transcode", "Manage transcode storage", "Clean up orphaned output files."),
    # --- groups ---
    Permission("group.view", "groups", "View groups", "See the TV group tree."),
    Permission("group.manage", "groups", "Manage groups", "Create, rename, move, and delete groups."),
    # --- nodes ---
    Permission("node.view", "nodes", "View nodes", "See remote site agents and their state."),
    Permission("node.manage", "nodes", "Manage nodes", "Enrol, rename, scan, and delete nodes."),
    # --- templates ---
    Permission("template.view", "templates", "View TV templates", "See installed templates and the community catalogue."),
    Permission("template.manage", "templates", "Manage TV templates", "Install, upload, and remove templates."),
    # --- schedule ---
    Permission("schedule.view", "schedule", "View operating hours", "See the site-wide playback window."),
    Permission("schedule.manage", "schedule", "Manage operating hours", "Change the site-wide playback window."),
    # --- audit ---
    Permission("event.view", "events", "View events", "See playback and device events."),
    Permission("event.security.view", "events", "View security events", "See logins, denials, and user changes."),
    # --- whole-installation operations ---
    Permission("tv.transfer", "tvs", "Export and import TVs", "Download or restore the configuration of every screen."),
    Permission("schedule.site.manage", "schedule", "Manage the site window", "Change the operating hours that apply installation-wide."),
    Permission("media.defaults.manage", "media", "Manage upload defaults", "Change the sound and compression applied to every new clip."),
    Permission("node.enrol", "nodes", "Enrol and remove nodes", "Create a node, issuing its enrolment token, or delete one."),
    # --- administration ---
    Permission("user.manage", "admin", "Manage users", "Create users, change roles, and reset passwords."),
    Permission("role.manage", "admin", "Manage roles", "Create roles and assign them to users."),
    Permission("diagnostics.view", "admin", "View diagnostics", "See runtime diagnostics."),
)

KEYS: frozenset[str] = frozenset(permission.key for permission in CATALOG)

# A permission is either meaningful over a branch or meaningful only over the
# whole installation. The distinction is not decoration: `require_permission`
# checks the flat permission set, which cannot tell where a grant came from, so
# without it a grant over one branch satisfied every gate. That is how a branch
# operator could export the configuration -- names, addresses, control URLs --
# of every screen in the company.
#
# Gates on these keys demand a *global* grant. Everything else is scoped, and
# the object it applies to is narrowed afterwards by ensure_covers/visible_*.
GLOBAL_ONLY: frozenset[str] = frozenset(
    {
        "tv.transfer",
        "tv.scan",
        "schedule.site.manage",
        "media.defaults.manage",
        "node.enrol",
        "transcode.manage",
        "template.view",
        "template.manage",
        "event.security.view",
        "user.manage",
        # role.manage is deliberately NOT here. Handing out access inside your
        # own branch is the zone of responsibility this model exists to give,
        # and ensure_may_grant already stops a branch administrator granting
        # beyond their own scope. Accounts stay central: user.manage is global.
        "diagnostics.view",
    }
)

BY_KEY: dict[str, Permission] = {permission.key: permission for permission in CATALOG}

# Reading is the floor: every built-in role can look at the panel.
_VIEWER: frozenset[str] = frozenset(
    {
        "tv.view",
        "media.view",
        "playlist.view",
        "transcode.view",
        "group.view",
        "schedule.view",
        "event.view",
    }
)

# What "operator" meant when it was level 2.
_OPERATOR: frozenset[str] = _VIEWER | {
    "tv.command",
    "media.upload",
    "media.manage",
    "playlist.edit",
    # Deliberately not playlist.assign: putting a playlist on a screen used to
    # need tv.manage, which an operator never had. The branch presets in the
    # next stage are where it belongs.
    "transcode.rebuild",
    "event.security.view",
    # media.defaults.manage only because `media.manage` used to guard the
    # site-wide upload defaults, and an operator could set them. Deliberately
    # NOT schedule.manage: operating hours were admin-only before this and
    # must stay that way.
    "media.defaults.manage",
}

BUILTIN_ROLES: dict[str, frozenset[str]] = {
    "viewer": _VIEWER,
    "operator": _OPERATOR,
    "admin": KEYS,
}

BUILTIN_ROLE_DESCRIPTIONS: dict[str, str] = {
    "viewer": "Read-only access to screens, media, playlists, and playback events.",
    "operator": "Everything a viewer can do, plus playback control, uploads, and playlist edits.",
    "admin": "Full access, including users, roles, devices, and templates.",
}

# Order matters: `users.role` is derived back from a user's permissions for API
# compatibility, and the strongest match must win.
BUILTIN_ROLE_ORDER: tuple[str, ...] = ("admin", "operator", "viewer")


def is_known(key: str) -> bool:
    return key in KEYS


def normalise(keys: object) -> frozenset[str]:
    """Keep only permissions that exist, dropping anything unrecognised.

    Grants are rows and rows outlive code. A permission removed in a later
    version must not be able to crash authorisation for everybody holding it.
    """
    if not isinstance(keys, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(key) for key in keys if str(key) in KEYS)


def derived_role(granted: frozenset[str]) -> str:
    """The closest built-in role name for a permission set.

    `users.role` stays in API responses and in the UI, so a user holding a
    custom role still needs a label. Reports the strongest built-in role whose
    permissions are all present.
    """
    for name in BUILTIN_ROLE_ORDER:
        if BUILTIN_ROLES[name] <= granted:
            return name
    return "viewer"


GLOBAL = "global"
GROUP = "group"
NODE = "node"
SCOPE_TYPES = (GLOBAL, GROUP, NODE)


class Scopes:
    """Answers "does this person hold this permission over this object".

    Built once per request from the user's grants and the shape of the group
    tree, because a dashboard asks the question for every screen it lists and
    walking the tree per screen would be one recursive query each.

    A grant on a group covers that group and everything beneath it, so an
    object in group X is covered by a grant on any of X's ancestors. A grant on
    a node covers the screens attached to that node. `global` covers all.
    """

    __slots__ = ("_by_permission", "_ancestors", "_parents")

    def __init__(self, grants: tuple[tuple[str, str, int | None], ...], group_parents: dict[int, int | None]):
        self._parents = group_parents
        self._ancestors: dict[int | None, frozenset[int]] = {}
        by_permission: dict[str, dict[str, set[int | None]]] = {}
        for permission, scope_type, scope_id in grants:
            if scope_type not in SCOPE_TYPES:
                continue
            slot = by_permission.setdefault(permission, {})
            slot.setdefault(scope_type, set()).add(scope_id)
        self._by_permission = by_permission

    def ancestors(self, group_id: int | None) -> frozenset[int]:
        """A group and everything above it, so a grant on a parent counts."""
        if group_id is None:
            return frozenset()
        cached = self._ancestors.get(group_id)
        if cached is not None:
            return cached
        chain: set[int] = set()
        current: int | None = group_id
        # The tree is depth-limited and the map is complete, but a corrupt
        # parent pointer must not spin forever.
        while current is not None and current not in chain:
            chain.add(current)
            current = self._parents.get(current)
        frozen = frozenset(chain)
        self._ancestors[group_id] = frozen
        return frozen

    def holds_anywhere(self, permission: str) -> bool:
        return permission in self._by_permission

    def holds_globally(self, permission: str) -> bool:
        return None in self._by_permission.get(permission, {}).get(GLOBAL, set()) or bool(
            self._by_permission.get(permission, {}).get(GLOBAL)
        )

    def covers(self, permission: str, *, group_id: int | None = None, node_id: int | None = None) -> bool:
        slot = self._by_permission.get(permission)
        if not slot:
            return False
        if slot.get(GLOBAL):
            return True
        granted_groups = slot.get(GROUP)
        if granted_groups and self.ancestors(group_id) & {gid for gid in granted_groups if gid is not None}:
            return True
        granted_nodes = slot.get(NODE)
        if granted_nodes and node_id is not None and node_id in granted_nodes:
            return True
        return False

    def covers_tv(self, permission: str, tv: dict) -> bool:
        return self.covers(permission, group_id=tv.get("group_id"), node_id=tv.get("node_id"))

    def scopes_for(self, permission: str) -> dict[str, set[int | None]]:
        return self._by_permission.get(permission, {})


def sections() -> dict[str, list[Permission]]:
    """The catalogue grouped for display, preserving declaration order."""
    grouped: dict[str, list[Permission]] = {}
    for permission in CATALOG:
        grouped.setdefault(permission.section, []).append(permission)
    return grouped
