"""FatCat AM — digital asset manager for the content engine."""
from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime
from app.db import get_db
from app.auth import get_current_user, require_user
from app.models import User, DigitalAsset, Organization

router = APIRouter(prefix="/fatcat", tags=["fatcat"])


def _templates_dir():
    from pathlib import Path
    return Path(__file__).parent.parent / "templates"


def _page(assets, org_name="FatCat AM"):
    rows = ""
    for a in assets:
        rows += f"""<tr class="{a.status}">
  <td>{a.name}</td>
  <td><span class="badge badge-{a.asset_type or 'other'}">{a.asset_type or '—'}</span></td>
  <td><span class="badge badge-{a.status}">{a.status}</span></td>
  <td>{"<a href='" + a.url + "' target='_blank'>link</a>" if a.url else "—"}</td>
  <td>{a.notes or ''}</td>
  <td>{a.created_at.strftime('%b %d') if a.created_at else ''}</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FatCat AM — {org_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:20px;max-width:960px;margin:0 auto}}
h1{{font-size:22px;color:#d4a853;margin-bottom:4px}}
.sub{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
h2{{font-size:15px;color:#d4a853;margin:24px 0 12px;text-transform:uppercase;letter-spacing:1px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:#94a3b8;padding:8px 6px;border-bottom:1px solid #2d3f52;font-size:11px;text-transform:uppercase;letter-spacing:1px}}
td{{padding:8px 6px;border-bottom:1px solid #1e2a3a}}
tr:hover td{{background:#1a1a30}}
a{{color:#d4a853;text-decoration:none}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px}}
.badge-video{{background:#1e3a5f;color:#7bb8ff}}
.badge-podcast{{background:#3a1e5f;color:#c47bff}}
.badge-product{{background:#1e5f3a;color:#7bffc4}}
.badge-post{{background:#5f3a1e;color:#ffc47b}}
.badge-social{{background:#5f1e3a;color:#ff7bc4}}
.badge-planned{{background:#2d3f52;color:#94a3b8}}
.badge-recording{{background:#5f4a1e;color:#ffd47b}}
.badge-editing{{background:#3a5f3a;color:#7bff7b}}
.badge-published{{background:#1e5f2e;color:#7bffa4}}
form{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px}}
input,select,textarea{{background:#1a1a30;border:1px solid #2d3f52;color:#e2e8f0;padding:8px 12px;border-radius:6px;font-size:13px;font-family:inherit}}
input[type=text],input[type=url]{{flex:1 1 140px}}
textarea{{flex:1 1 200px;resize:vertical;min-height:36px}}
select{{flex:0 1 auto}}
button{{background:#d4a853;color:#1a1a2e;border:none;padding:8px 16px;border-radius:6px;font-weight:700;font-size:13px;cursor:pointer}}
button:hover{{background:#e4b863}}
.summary{{color:#94a3b8;font-size:12px;margin-bottom:12px}}
.empty{{color:#64748b;padding:40px;text-align:center;font-style:italic}}
</style>
</head>
<body>
<h1>🐈 FatCat AM</h1>
<p class="sub">Digital asset manager — the content engine</p>

<form method="POST" action="/fatcat/add">
  <input type="text" name="name" placeholder="Asset name" required>
  <select name="asset_type">
    <option value="">Type…</option>
    <option value="video">Video</option>
    <option value="podcast">Podcast</option>
    <option value="product">Product</option>
    <option value="post">Blog Post</option>
    <option value="social">Social Clip</option>
  </select>
  <select name="status">
    <option value="planned">Planned</option>
    <option value="recording">Recording</option>
    <option value="editing">Editing</option>
    <option value="published">Published</option>
  </select>
  <input type="url" name="url" placeholder="URL (optional)">
  <textarea name="notes" placeholder="Notes (optional)"></textarea>
  <button type="submit">+ Add</button>
</form>

<div class="summary">{len(assets)} assets</div>
<table>
<tr><th>Name</th><th>Type</th><th>Status</th><th>Link</th><th>Notes</th><th>Created</th></tr>
{"".join(rows) if rows else '<tr><td colspan="6" class="empty">No assets yet — add one above</td></tr>'}
</table>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
def list_assets(request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    assets = db.query(DigitalAsset).filter(
        DigitalAsset.org_id == user.org_id).order_by(
        DigitalAsset.created_at.desc()).all()
    org = db.query(Organization).filter(Organization.id == user.org_id).first()
    return _page(assets, org.name if org else "FatCat AM")


@router.post("/add")
def add_asset(name: str = Form(...),
              asset_type: str = Form(""),
              status: str = Form("planned"),
              url: str = Form(""),
              notes: str = Form(""),
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    a = DigitalAsset(
        org_id=user.org_id,
        name=name,
        asset_type=asset_type or None,
        status=status,
        url=url or None,
        notes=notes or None,
    )
    db.add(a)
    db.commit()
    return RedirectResponse(url="/fatcat", status_code=302)
