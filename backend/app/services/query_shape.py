# Path: app/services/query_shape.py
# File: query_shape.py
# Created: 2026-09-15
# Purpose: Query-shape guards (DWB-530) - turn a wrong query/path shape into a 400 that names the valid params, so it can never be confused with a legitimate empty result or a bare 404.
# Caller: app/routers/dwb_sessions.py, app/routers/tl_channel.py
# Callees: fastapi.HTTPException
# Data In: starlette Request (query params), allowed param names, endpoint label
# Data Out: None (raises HTTPException 400 on a wrong shape)
# Last Modified: 2026-09-15

"""Wrong-shape guards for read endpoints where "empty" is a real answer.

VTC feedback B2 (DWB-530): ``GET /api/sessions?project_id=X&status=open``
returned a bare 404 that read as "no open session" and nearly caused a
duplicate session open; ``GET /api/tl-channel/156`` 404'd the same way with no
hint whether the route or the row was missing. The rule these helpers enforce:

- wrong shape (unknown query param, collection form that does not exist)
  -> 400 whose detail names the valid params / routes;
- genuinely missing row -> 404 that names the entity (router-side);
- empty list -> 200 [] as before.

Usage in a router::

    @router.get("")
    def list_things(request: Request, limit: int = Query(...)):
        reject_unknown_query_params(request, {"limit"}, endpoint="GET /api/things")
"""

from collections.abc import Iterable

from fastapi import HTTPException, Request


def reject_unknown_query_params(
    request: Request,
    allowed: Iterable[str],
    *,
    endpoint: str,
) -> None:
    """Raise 400 naming the offending and the valid query params when the
    request carries any query param outside ``allowed``. No-op otherwise."""
    allowed_set = set(allowed)
    unknown = sorted(set(request.query_params.keys()) - allowed_set)
    if not unknown:
        return
    valid = ", ".join(sorted(allowed_set)) if allowed_set else "(none)"
    raise HTTPException(
        400,
        f"{endpoint}: unknown query param(s) {', '.join(unknown)}; "
        f"valid params: {valid}",
    )


def collection_form_not_available(endpoint: str, *, use: Iterable[str]) -> HTTPException:
    """400 for a collection-form GET that this API does not serve, pointing the
    caller at the routes that do. Returned (not raised) so the router can
    ``raise`` it explicitly at the call site."""
    return HTTPException(
        400,
        f"{endpoint} has no collection form; use " + " or ".join(use),
    )
