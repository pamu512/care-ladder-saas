"""P1: PendingAck.tenant_id on create; pending_list never treats None as all-tenants."""

from __future__ import annotations

from care_ladder.channels.ack import AckRegistry


def test_create_pending_sets_tenant_id():
    reg = AckRegistry(secret="t")
    p = reg.create_pending(
        "inc-a", "r1", "slack", "msg", 300, "https://x", tenant_id="tenant-a"
    )
    assert p.tenant_id == "tenant-a"
    assert reg.get_pending("inc-a", "r1").tenant_id == "tenant-a"


def test_pending_list_none_is_empty_not_all_tenants():
    reg = AckRegistry(secret="t")
    reg.create_pending("inc-a", "r1", "slack", "msg", 300, "https://x", tenant_id="tenant-a")
    reg.create_pending("inc-b", "r1", "slack", "msg", 300, "https://x", tenant_id="tenant-b")
    assert reg.pending_list(None) == []
    assert reg.pending_list() == []


def test_tenant_a_cannot_see_tenant_b_pending():
    reg = AckRegistry(secret="t")
    a = reg.create_pending(
        "inc-a", "r1", "slack", "help A", 300, "https://x", tenant_id="tenant-a"
    )
    b = reg.create_pending(
        "inc-b", "r1", "slack", "help B", 300, "https://x", tenant_id="tenant-b"
    )
    listed_a = reg.pending_list("tenant-a")
    listed_b = reg.pending_list("tenant-b")
    assert len(listed_a) == 1
    assert listed_a[0]["incident_id"] == "inc-a"
    assert listed_a[0]["tenant_id"] == "tenant-a"
    assert "token" not in listed_a[0], "raw ack token must not appear in list summaries"
    # ack_url may embed the capability token; the dedicated token field must stay absent.
    assert b.token not in str(listed_a)
    assert len(listed_b) == 1
    assert listed_b[0]["incident_id"] == "inc-b"


def test_unscoped_pending_not_leaked_into_tenant_view():
    reg = AckRegistry(secret="t")
    reg.create_pending("inc-x", "r1", "slack", "msg", 300, "https://x")  # tenant_id None
    reg.create_pending(
        "inc-a", "r1", "slack", "msg", 300, "https://x", tenant_id="tenant-a"
    )
    listed = reg.pending_list("tenant-a")
    assert len(listed) == 1
    assert listed[0]["incident_id"] == "inc-a"


def test_cross_tenant_summary_omits_raw_token():
    """Tenant B list cannot discover tenant A's pending (or raw token field)."""
    reg = AckRegistry(secret="t")
    a = reg.create_pending(
        "inc-a", "r1", "telegram", "page", 300, "https://x", tenant_id="tenant-a"
    )
    assert reg.pending_list("tenant-b") == []
    row = reg.pending_list("tenant-a")[0]
    assert "token" not in row
    assert a.token not in str(reg.pending_list("tenant-b"))
