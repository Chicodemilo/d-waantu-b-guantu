"""Tests for GET /api/status."""


def test_status_returns_200(client):
    r = client.get("/api/status")
    assert r.status_code == 200


def test_status_response_shape(client):
    data = client.get("/api/status").json()
    assert isinstance(data["healthy"], bool)
    assert isinstance(data["active_agents"], int)
    assert isinstance(data["open_alerts"], int)
    assert isinstance(data["in_progress_tickets"], int)
    assert set(data.keys()) == {"healthy", "active_agents", "open_alerts", "in_progress_tickets"}


def test_status_healthy_is_true(client):
    data = client.get("/api/status").json()
    assert data["healthy"] is True


def test_status_counts_reflect_data(client, make_agent, make_ticket):
    """Create known data and verify status counts match."""
    # Create an active agent
    make_agent(is_active=True)
    # Create an in_progress ticket
    make_ticket(status="in_progress")

    data = client.get("/api/status").json()
    assert data["active_agents"] >= 1
    assert data["in_progress_tickets"] >= 1
