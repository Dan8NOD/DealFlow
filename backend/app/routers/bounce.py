"""
Bounce matching — find alternate properties for leads whose target property is rented.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.auth import get_current_user
from app.models import User, Lead, Property, PropertyStatus

router = APIRouter(prefix="/api/bounce", tags=["bounce"])


def normalize_addr(addr: str) -> str:
    """Extract street number + name for area matching."""
    import re
    addr = (addr or "").lower()
    # Keep just the street part, strip city/state
    parts = addr.split(",")[0].strip()
    return parts


@router.get("/suggestions")
async def bounce_suggestions(
    lead_id: int = Query(None),
    property_id: int = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    For a lead or property, find similar AVAILABLE properties to bounce to.
    If the lead's target property is RENTED, suggest alternates.
    """
    org_id = user.org_id

    # Resolve: find the property
    prop = None
    if property_id:
        prop = db.query(Property).filter(Property.id == property_id, Property.org_id == org_id).first()
    elif lead_id:
        lead = db.query(Lead).filter(Lead.id == lead_id, Lead.org_id == org_id).first()
        if lead and lead.property_id:
            prop = db.query(Property).filter(Property.id == lead.property_id, Property.org_id == org_id).first()

    if not prop:
        return {"suggestions": [], "reason": "No target property found"}

    # Only suggest bounces if the property is RENTED, OCCUPIED, or OFF_MARKET
    target_status = prop.status.value if prop.status else ""
    is_bounce_candidate = target_status in ("RENTED", "OCCUPIED", "OFF_MARKET")

    # Get target property specs for matching
    target_br = prop.bedrooms
    target_ba = prop.bathrooms
    target_rent = prop.rent or 0
    target_city = (prop.city or "").lower()
    target_addr = normalize_addr(prop.address)

    # Find available properties with similar specs
    candidates = db.query(Property).filter(
        Property.org_id == org_id,
        Property.status == "AVAILABLE",
        Property.id != prop.id,
    ).all()

    scored = []
    for c in candidates:
        score = 0
        reasons = []

        # BR match (exact = best)
        if target_br and c.bedrooms:
            if c.bedrooms == target_br:
                score += 40
                reasons.append(f"Same BR ({int(target_br)})")
            elif abs(c.bedrooms - target_br) <= 1:
                score += 20
                reasons.append(f"Similar BR ({int(c.bedrooms)})")

        # BA match
        if target_ba and c.bathrooms:
            if c.bathrooms == target_ba:
                score += 25
                reasons.append(f"Same BA ({target_ba})")
            elif abs(c.bathrooms - target_ba) <= 0.5:
                score += 12

        # Rent match (±20%)
        if target_rent > 0 and c.rent and c.rent > 0:
            diff_pct = abs(c.rent - target_rent) / target_rent
            if diff_pct <= 0.10:
                score += 20
                reasons.append(f"Similar rent (${int(c.rent)})")
            elif diff_pct <= 0.25:
                score += 10

        # Same city
        c_city = (c.city or "").lower()
        if target_city and c_city and target_city == c_city:
            score += 10
            reasons.append("Same city")

        # Nearby: same street prefix (first word of street name)
        c_addr = normalize_addr(c.address)
        if target_addr and c_addr:
            target_street = target_addr.split()
            c_street = c_addr.split()
            if len(target_street) > 1 and len(c_street) > 1:
                if target_street[1] == c_street[1]:  # Same street name
                    score += 5
                    reasons.append("Same street")

        if score > 0:
            scored.append({
                "property_id": c.id,
                "address": c.address,
                "unit": c.unit or "",
                "city": c.city or "",
                "rent": c.rent,
                "bedrooms": c.bedrooms,
                "bathrooms": c.bathrooms,
                "score": score,
                "reasons": reasons,
            })

    # Sort by score descending, top 8
    scored.sort(key=lambda x: -x["score"])
    top = scored[:8]

    return {
        "target_property": {
            "id": prop.id,
            "address": prop.address,
            "unit": prop.unit or "",
            "status": target_status,
            "rent": prop.rent,
            "bedrooms": prop.bedrooms,
            "bathrooms": prop.bathrooms,
        },
        "is_bounce_candidate": is_bounce_candidate,
        "reason": f"Property is {target_status}" if is_bounce_candidate else f"Property is {target_status} — bounce not needed",
        "suggestions": top,
    }


@router.get("/leads-to-bounce")
async def leads_to_bounce(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, le=200),
):
    """
    Find all leads that could be bounced: leads linked to RENTED/OCCUPIED properties.
    """
    org_id = user.org_id

    # Find leads whose property is rented
    results = db.query(Lead, Property).join(
        Property, Lead.property_id == Property.id
    ).filter(
        Lead.org_id == org_id,
        Property.org_id == org_id,
        Property.status.in_(["RENTED", "OCCUPIED", "OFF_MARKET"]),
    ).order_by(Lead.received_at.desc()).limit(limit).all()

    output = []
    for lead, prop in results:
        output.append({
            "id": lead.id,  # needed for row selection in grid
            "lead_id": lead.id,
            "lead_name": lead.name,
            "lead_email": lead.email,
            "lead_phone": lead.phone,
            "lead_status": lead.status.value if lead.status else "",
            "property_id": prop.id,
            "property_address": prop.address,
            "property_unit": prop.unit or "",
            "property_status": prop.status.value if prop.status else "",
            "property_rent": prop.rent,
            "property_bedrooms": prop.bedrooms,
            "property_bathrooms": prop.bathrooms,
            "received_at": lead.received_at.isoformat() if lead.received_at else None,
        })

    return {
        "count": len(output),
        "leads": output,
    }