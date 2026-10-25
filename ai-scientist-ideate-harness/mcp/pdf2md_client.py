#!/usr/bin/env python3
"""pdf2md async client — submit PDFs to a remote marker-pdf server via /jobs + polling.

Cloudflare cuts any request at 100s, so POST /convert (which blocks until done)
524s on real papers. This client only ever makes short requests.

Usage:
    python pdf2md_client.py <pdf-or-dir> [more...] [options]

Env:
    PDF2MD_SERVER   default https://pdf2md.fixcollege.xyz
    PDF2MD_API_KEY  required
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import json
import zipfile
import io
import urllib.request
import urllib.error
import uuid
from pathlib import Path

DEFAULT_SERVER = "https://pdf2md.fixcollege.xyz"


def _request(url, key, method="GET", body=None, content_type=None, timeout=90):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("X-API-Key", key)
    # Cloudflare rejects requests with urllib's default User-Agent
    req.add_header("User-Agent", "pdf2md-client/1.0")
    if content_type:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


def _multipart(fields, filename, filedata):
    """Build a multipart/form-data body."""
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        if v is None:
            continue
        out.write(f"--{boundary}\r\n".encode())
        out.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        out.write(f"{v}\r\n".encode())
    out.write(f"--{boundary}\r\n".encode())
    out.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    out.write(b"Content-Type: application/pdf\r\n\r\n")
    out.write(filedata)
    out.write(f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def submit(server, key, pdf: Path, opts):
    fields = {
        "output_format": opts.output_format,
        "extract_images": str(opts.extract_images).lower(),
        "force_ocr": str(opts.force_ocr).lower(),
        "paginate_output": str(opts.paginate).lower(),
    }
    if opts.page_range:
        fields["page_range"] = opts.page_range
    body, ctype = _multipart(fields, pdf.name, pdf.read_bytes())
    status, data, _ = _request(f"{server}/jobs", key, "POST", body, ctype, timeout=180)
    return json.loads(data)


def poll(server, key, job_id, interval=5, timeout=3600, verbose=True):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        _, data, _ = _request(f"{server}/jobs/{job_id}", key, timeout=30)
        info = json.loads(data)
        st = info.get("status")
        if verbose and st != last:
            print(f"    [{int(time.time()-t0):>4}s] {st}", flush=True)
            last = st
        if st in ("done", "completed", "success"):
            return info
        if st in ("error", "failed"):
            raise RuntimeError(info.get("error") or info)
        time.sleep(interval)
    raise TimeoutError(f"job {job_id} still {last} after {timeout}s")


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def download(server, key, job_id, outdir: Path, stem: str, figures_dir: Path | None = None):
    _, data, _ = _request(f"{server}/jobs/{job_id}/download", key, timeout=180)
    outdir.mkdir(parents=True, exist_ok=True)
    written, renamed, md_target = [], {}, None
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            base = Path(name).name
            if base.endswith(".md"):
                target = md_target = outdir / f"{stem}.md"  # the main .md gets the pdf's stem
            elif figures_dir is not None and base.lower().endswith(IMAGE_EXT):
                # marker names images the same way in every paper (_page_3_Figure_1.jpeg), so in a shared folder they
                # must carry the paper's stem or one paper overwrites another's figures
                figures_dir.mkdir(parents=True, exist_ok=True)
                target = figures_dir / f"{stem}_{base}"
                renamed[name] = os.path.relpath(target, outdir)
                renamed.setdefault(base, renamed[name])
            else:
                target = outdir / base  # images keep their own names when no figures_dir is given
            target.write_bytes(z.read(name))
            written.append(target)
    if md_target is not None and renamed:
        text = md_target.read_text(encoding="utf-8", errors="replace")
        for old, new in sorted(renamed.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(f"]({old})", f"]({new})")
        md_target.write_text(text, encoding="utf-8")
    return written


def collect(paths):
    pdfs = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            pdfs += sorted(x for x in p.rglob("*.pdf") if x.is_file())
        elif p.is_file():
            pdfs.append(p)
        else:
            print(f"!! not found: {p}", file=sys.stderr)
    return pdfs


def main():
    ap = argparse.ArgumentParser(description="Convert PDFs to Markdown via a remote pdf2md server.")
    ap.add_argument("paths", nargs="+", help="PDF files and/or directories")
    ap.add_argument("-o", "--outdir", help="output dir (default: alongside each PDF)")
    ap.add_argument("--skip-existing", action="store_true", help="skip PDFs whose .md already exists")
    ap.add_argument("--output-format", default="markdown", choices=["markdown", "html", "json", "chunks"])
    ap.add_argument("--page-range", help="0-based, e.g. 0,5-10,20")
    ap.add_argument("--force-ocr", action="store_true")
    ap.add_argument("--paginate", action="store_true", help="separate pages with a numbered rule")
    ap.add_argument("--no-images", dest="extract_images", action="store_false", default=True)
    ap.add_argument("--figures-dir", help="put extracted images here as <pdf stem>_<name> (links in the .md are rewritten)")
    ap.add_argument("--interval", type=float, default=5, help="poll interval, seconds")
    ap.add_argument("--timeout", type=int, default=3600, help="per-job timeout, seconds")
    ap.add_argument("--server", default=os.environ.get("PDF2MD_SERVER", DEFAULT_SERVER))
    ap.add_argument("--api-key", default=os.environ.get("PDF2MD_API_KEY"))
    opts = ap.parse_args()

    if not opts.api_key:
        sys.exit("error: set PDF2MD_API_KEY (or pass --api-key)")
    server = opts.server.rstrip("/")

    pdfs = collect(opts.paths)
    if not pdfs:
        sys.exit("error: no PDFs found")

    ok = fail = skip = 0
    for i, pdf in enumerate(pdfs, 1):
        outdir = Path(opts.outdir).expanduser() if opts.outdir else pdf.parent
        md = outdir / f"{pdf.stem}.md"
        print(f"[{i}/{len(pdfs)}] {pdf.name}", flush=True)
        if opts.skip_existing and md.exists():
            print("    skip (md exists)")
            skip += 1
            continue
        try:
            job = submit(server, opts.api_key, pdf, opts)
            jid = job.get("id") or job.get("job_id")
            print(f"    job {jid}", flush=True)
            poll(server, opts.api_key, jid, opts.interval, opts.timeout)
            figs = Path(opts.figures_dir).expanduser() if opts.figures_dir else None
            files = download(server, opts.api_key, jid, outdir, pdf.stem, figs)
            print(f"    -> {md}  ({len(files)} file(s))", flush=True)
            ok += 1
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            fail += 1

    print(f"\ndone: {ok} converted, {skip} skipped, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
