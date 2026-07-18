"""NOD on the Streets — $100 live haggling contest."""
from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import get_current_user
from app.models import User, StreetContestEntry

router = APIRouter(prefix="/streets", tags=["streets"])


@router.post("/submit")
def submit_entry(name: str = Form(...), text: str = Form(...), db: Session = Depends(get_db)):
    entry = StreetContestEntry(name=name[:200], text=text)
    db.add(entry)
    db.commit()
    return {"ok": True, "id": entry.id}


def _html(entries):
    rows = ""
    for e in entries:
        rows += f"""
<tr>
  <td>{e.name}</td>
  <td>{e.text[:120]}{'...' if len(e.text) > 120 else ''}</td>
  <td>{'✅' if e.contacted else '—'}</td>
  <td>{e.created_at.strftime('%b %d %I:%M%p') if e.created_at else ''}</td>
</tr>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NOD Streets — Admin</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:20px;max-width:960px;margin:0 auto}}
h1{{font-size:22px;color:#34d399;margin-bottom:4px}}
.sub{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:#94a3b8;padding:8px 6px;border-bottom:1px solid #2d3f52;font-size:11px;text-transform:uppercase;letter-spacing:1px}}
td{{padding:8px 6px;border-bottom:1px solid #1e2a3a}}
tr:hover td{{background:#1a1a30}}
.count{{color:#94a3b8;font-size:12px;margin-bottom:12px}}
</style>
</head>
<body>
<h1>🎤 NOD on the Streets</h1>
<p class="sub">${len(entries)} entries — pick contenders for the live \$100 haggling showdown</p>
<table>
<tr><th>Name</th><th>Contact</th><th>Reached</th><th>Date</th></tr>
{rows}
</table>
</body></html>"""


@router.get("", response_class=HTMLResponse)
def list_entries(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entries = db.query(StreetContestEntry).order_by(StreetContestEntry.created_at.desc()).all()
    return _html(entries)
